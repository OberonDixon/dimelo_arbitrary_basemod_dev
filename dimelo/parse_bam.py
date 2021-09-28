r"""
=================================================
Functions to parse input bams.
=================================================
"""

# import multiprocessing

import numpy as np
import pandas as pd
import pysam

# from joblib import Parallel, delayed

####################################################################################
# classes for regions & methylation information
####################################################################################


class Region(object):
    def __init__(self, region):
        self.chromosome = region[1][0]
        self.begin = region[1][1]
        self.end = region[1][2]
        self.size = self.end - self.begin
        self.string = f"{self.chromosome}_{self.begin}_{self.end}"
        # strand of motif to orient single molecules
        self.strand = region[1][3]


class Methylation(object):
    def __init__(self, table, data_type, name, called_sites):
        self.table = table
        self.data_type = data_type
        self.name = name
        self.called_sites = called_sites


# dictionary summarizing aggreate as go
# class AggregateDict(object):
#    def __init__(self, dict):
#        self.dict = dictionary

# global dictionary update
ave_dict = {}

####################################################################################
# extracting modified base info from bams
####################################################################################


def parse_bam(
    fileName,
    sampleName,
    bedFile=None,
    basemod="A+CG",
    center=False,
    windowSize=None,
    region=None,
    threshA=128,
    threshC=128,
):
    """Create methylation object. Process windows in parallel.
    Args:
            :param fileName: name of bam file with Mm and Ml tags
            :param sampleName: name of sample for output file name labelling
            :param bedFile: name of bed file that defines regions of interest
            :param basemod: which basemod, currently supported options are 'A', 'CG', 'A+CG'
            :param center: report positions with respect to reference center (+/- window size) if True or in original reference space if False
            :param windowSize: window size around center point of feature of interest to plot (+/-); only mods within this window are stored; only specify if center=True
            :param threshA: threshold above which to call an A base methylated
            :param threshC: threshold above which to call a C base methylated
    Return:
            dataframe with: read_name, strand, chr, position, probability, mod
            dictionary with aggregate data: {pos:modification: [methylated_bases, total_bases]}
    """
    global ave_dict
    if bedFile is not None:
        # make a region object for each row of bedFile
        bed = pd.read_csv(bedFile, sep="\t", header=None)
        windows = []
        for row in bed.iterrows():
            windows.append(Region(row))

        # num_cores = multiprocessing.cpu_count()
        # meth_data = Parallel(n_jobs=num_cores)(
        #     delayed(parse_ont_bam_by_window)(
        #         fileName,
        #         sampleName,
        #         basemod,
        #         windowSize,
        #         w,
        #         center,
        #         threshA,
        #         threshC,
        #     )
        #     for w in windows
        # )

        # test not in parallel
        meth_data = []
        for w in windows:
            meth_data.append(
                parse_ont_bam_by_window(
                    fileName,
                    sampleName,
                    basemod,
                    windowSize,
                    w,
                    center,
                    threshA,
                    threshC,
                )
            )

        list_tables = []
        for m in meth_data:
            list_tables.append(m.table)
        all_data = pd.concat(list_tables)

        return all_data, ave_dict
        # return all_data, AggregateDict.dict

    if region is not None:
        return parse_ont_bam_by_window(
            fileName,
            sampleName,
            basemod,
            windowSize,
            region,
            center,
            threshA,
            threshC,
        )


def parse_ont_bam_by_window(
    fileName, sampleName, basemod, windowSize, window, center, threshA, threshC
):
    """Create methylation object for each window.
    Args:
            :param fileName: name of bam file with Mm and Ml tags
            :param sampleName: name of sample for output file name labelling
            :param basemod: which basemods, currently supported options are 'A', 'CG', 'A+CG'
            :param windowSize: window size around center point of feature of interest to plot (+/-); only mods within this window are stored; only applicable for center=True
            :param window: window from bed file
            :param center: report positions with respect to reference center (+/- window size) if True or in original reference space if False
            :param threshA: threshold above which to call an A base methylated
            :param threshC: threshold above which to call a C base methylated
    Return:
            methylation object for a given window
    """
    bam = pysam.AlignmentFile(fileName, "rb")
    data = []
    for read in bam.fetch(
        reference=window.chromosome, start=window.begin, end=window.end
    ):
        [
            (mod, positions, probs),
            (mod2, positions2, probs2),
        ] = get_modified_reference_positions(
            read, basemod, window, center, threshA, threshC, windowSize
        )
        for pos, prob in zip(positions, probs):
            if pos is not None:
                if (center is True and abs(pos) <= windowSize) or (
                    center is False and pos > window.begin and pos < window.end
                ):  # to decrease memory, only store bases within the window
                    data.append(
                        (
                            read.query_name,
                            "-" if read.is_reverse else "+",
                            window.chromosome,
                            pos,
                            prob,
                            mod,
                        )
                    )
        for pos, prob in zip(positions2, probs2):
            if pos is not None:
                if (center is True and abs(pos) <= windowSize) or (
                    center is False and pos > window.begin and pos < window.end
                ):  # to decrease memory, only store bases within the window
                    data.append(
                        (
                            read.query_name,
                            "-" if read.is_reverse else "+",
                            window.chromosome,
                            pos,
                            prob,
                            mod2,
                        )
                    )
    data_return = Methylation(
        table=pd.DataFrame(
            data, columns=["read_name", "strand", "chr", "pos", "prob", "mod"]
        )
        .astype(
            dtype={
                "read_name": "category",
                "strand": "category",
                "chr": "category",
                "mod": "category",
                "prob": "int16",
            }
        )
        .sort_values(["read_name", "pos"]),
        data_type="ont-bam",
        name=sampleName,
        called_sites=len(data),
    )
    return data_return


def get_modified_reference_positions(
    read, basemod, window, center, threshA, threshC, windowSize
):
    """Extract mA and mC pos & prob information for the read
    Args:
            :param read: single read from bam file
            :param basemod: which basemods, currently supported options are 'A', 'CG', 'A+CG'
            :param window: window from bed file
            :param center: report positions with respect to reference center (+/- window size) if True or in original reference space if False
            :param threshA: threshold above which to call an A base methylated
            :param threshC: threshold above which to call a C base methylated
            :param windowSize: window size around center point of feature of interest to plot (+/-); only mods within this window are stored; only applicable for center=True
    """
    if (read.has_tag("Mm")) & (";" in read.get_tag("Mm")):
        mod1 = read.get_tag("Mm").split(";")[0].split(",", 1)[0]
        mod2 = read.get_tag("Mm").split(";")[1].split(",", 1)[0]
        mod1_list = read.get_tag("Mm").split(";")[0].split(",", 1)
        mod2_list = read.get_tag("Mm").split(";")[1].split(",", 1)
        base = basemod[0]  # this will be A, C, or A
        if basemod == "A+CG":
            base2 = basemod[2]  # this will be C for A+C case
        else:  # in the case of a single mod will just be checking that single base
            base2 = base
        if len(mod1_list) > 1 and (base in mod1 or base2 in mod1):
            mod1_return = get_mod_reference_positions_by_mod(
                read, mod1, 0, window, center, threshA, threshC, windowSize
            )
        else:
            mod1_return = (None, [None], [None])
        if len(mod2_list) > 1 and (base in mod2 or base2 in mod2):
            mod2_return = get_mod_reference_positions_by_mod(
                read, mod2, 1, window, center, threshA, threshC, windowSize
            )
            return (mod1_return, mod2_return)
        else:
            return (mod1_return, (None, [None], [None]))
    else:
        return ((None, [None], [None]), (None, [None], [None]))


def get_mod_reference_positions_by_mod(
    read, basemod, index, window, center, threshA, threshC, windowSize
):
    """Get positions and probabilities of modified bases for a single read
    Args:
            :param read: one read in bam file
            :param mod: which basemod, reported as base+x/y/m
            :param window: window from bed file
            :param center: report positions with respect to reference center (+/- window size) if True or in original reference space if False
            :param threshA: threshold above which to call an A base methylated
            :param threshC: threshold above which to call a C base methylated
            :param windowSize: window size around center point of feature of interest to plot (+/-); only mods within this window are stored; only applicable for center=True
    """
    base, mod = basemod.split("+")
    deltas = [
        int(i) for i in read.get_tag("Mm").split(";")[index].split(",")[1:]
    ]
    num_base = len(read.get_tag("Mm").split(";")[index].split(",")) - 1
    Ml = read.get_tag("Ml")
    if index == 0:
        probabilities = np.array(Ml[0:num_base], dtype=int)
    if index == 1:
        probabilities = np.array(Ml[0 - num_base :], dtype=int)
    base_index = np.array(
        [
            i
            for i, letter in enumerate(read.get_forward_sequence())
            if letter == base
        ]
    )
    # determine locations of the modified bases, where index_adj is the adjustment of the base_index
    # based on the cumulative sum of the deltas
    locations = np.cumsum(deltas)
    # loop through locations and increment index_adj by the difference between the next location and current one + 1
    # if the difference is zero, therefore, the index adjustment just gets incremented by one because no base should be skipped
    index_adj = []
    index_adj.append(locations[0])
    i = 0
    for i in range(len(locations) - 1):
        diff = locations[i + 1] - locations[i]
        index_adj.append(index_adj[i] + diff + 1)
    # get the indices of the modified bases
    modified_bases = base_index[index_adj]
    refpos = np.array(read.get_reference_positions(full_length=True))
    if read.is_reverse:
        refpos = np.flipud(refpos)
        probabilities = probabilities[::-1]

    # extract CpG sites only rather than all mC
    keep = []
    prob_keep = []
    all_bases_index = []
    i = 0
    seq = read.get_forward_sequence()
    # deal with None for refpos from soft clipped / unaligned bases
    if "C" in basemod:
        for b in base_index:
            if (
                b < len(seq) - 1
            ):  # if modified C is not the last base in the read
                if (refpos[b] is not None) & (refpos[b + 1] is not None):
                    if seq[b + 1] == "G":
                        if (
                            abs(refpos[b + 1] - refpos[b]) == 1
                        ):  # ensure there isn't a gap
                            all_bases_index.append(
                                b
                            )  # add to all_bases_index whether or not modified
                            if b in modified_bases:
                                if probabilities[i] >= threshC:
                                    keep.append(b)
                                    prob_keep.append(i)
            # increment for each instance of modified base
            if b in modified_bases:
                i = i + 1
    else:  # for m6A no need to look at neighboring base; do need to remove refpos that are None
        for b in base_index:
            if refpos[b] is not None:
                all_bases_index.append(
                    b
                )  # add to all_bases_index whether or not modified
                if b in modified_bases:
                    if probabilities[i] >= threshA:
                        keep.append(b)
                        prob_keep.append(i)
            # increment for each instance of modified base
            if b in modified_bases:
                i = i + 1
    # adjust position to be centered at 0 at the center of the motif; round in case is at 0.5
    # add returning base_index for plotting mod/base_abundance
    if center is True:
        if window.strand == "+":
            refpos_mod_adjusted = np.array(refpos[keep]) - round(
                ((window.end - window.begin) / 2 + window.begin)
            )
            refpos_total_adjusted = np.array(refpos[all_bases_index]) - round(
                ((window.end - window.begin) / 2 + window.begin)
            )
        if window.strand == "-":
            refpos_mod_adjusted = -1 * (
                np.array(refpos[keep])
                - round(((window.end - window.begin) / 2 + window.begin))
            )
            refpos_total_adjusted = -1 * (
                np.array(refpos[all_bases_index])
                - round(((window.end - window.begin) / 2 + window.begin))
            )
        update_ave_dict(
            refpos_mod_adjusted,
            refpos_total_adjusted,
            basemod,
            center,
            windowSize,
            window,
        )
        return (basemod, refpos_mod_adjusted, probabilities[prob_keep])
    else:
        update_ave_dict(
            refpos[keep], refpos[all_bases_index], center, windowSize, window
        )
        return (basemod, np.array(refpos[keep]), probabilities[prob_keep])


def update_ave_dict(
    refpos_mod, refpos_total, basemod, center, windowSize, window
):
    """
    {pos:modification: [methylated_bases, total_bases]}
    """
    global ave_dict
    for pos in refpos_total:
        # only store positions within window
        if (center is True and abs(pos) <= windowSize) or (
            center is False and pos > window.begin and pos < window.end
        ):
            # key is pos:mod
            key = str(pos) + ":" + basemod
            # increment if the key is already in the dictionary
            if key in ave_dict:
                ave_dict[key][1] += 1
                # increment modified cout if in modified list
                if pos in refpos_mod:
                    ave_dict[key][0] += 1
            # add value of 1 if the key is not already in the dictionary
            else:
                if pos in refpos_mod:
                    ave_dict[key] = [1, 1]
                else:
                    ave_dict[key] = [0, 1]
    return ave_dict
