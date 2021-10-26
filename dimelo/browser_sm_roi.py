# code adapted from methplotlib
# https://doi.org/10.1093/bioinformatics/btaa093

import sqlite3
import sys

import matplotlib.pyplot as plt
import pandas as pd
import plotly
import plotly.graph_objs as go
import pyranges as pr
import seaborn as sns

from dimelo.parse_bam import parse_bam

# import plotly.io as pio

COLOR_A = "#053C5E"
COLOR_C = "#BB4430"
DEFAULT_THRESH_A = 128
DEFAULT_THRESH_C = 128


class DataTraces(object):
    def __init__(self, traces, names):
        self.traces = traces
        self.names = names
        self.index = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.index == len(self.traces):
            raise StopIteration
        else:
            self.index += 1
            return self.traces[self.index - 1]


class Region(object):
    def __init__(self, region, fasta=None):
        if ":" in region:
            try:
                self.chromosome, interval = region.replace(",", "").split(":")
                self.begin, self.end = [int(i) for i in interval.split("-")]
            except ValueError:
                sys.exit(
                    "\n\nERROR: Window (-w/--window) inproperly formatted, "
                    "examples of accepted formats are:\n"
                    "'chr5:150200605-150423790'\n\n"
                )
            self.size = self.end - self.begin
            self.string = f"{self.chromosome}_{self.begin}_{self.end}"


def browser_sm_roi(
    fileNames,
    sampleNames,
    window,
    basemod,
    outDir,
    threshA=128,
    threshC=128,
    bedFileFeatures=None,
    smooth=1000,
    min_periods=100,
    colorA=COLOR_A,
    colorC=COLOR_C,
    dotsize=4,
    static=False,
):
    """
    Create single molecule plots within a region of interest
    Args:
            :param fileNames: list of names of bam files with Mm and Ml tags; indexed
            :param sampleNames: list of names of samples for output plot name labelling
            :param window: formatted as for example: "chr1:1-100000"
            :param basemod: which basemods, currently supported options are 'A', 'CG', 'A+CG'
            :param outDir: directory to output plot
            :param threshA: threshold for calling mA; default 128
            :param threshC: threshold for calling mCG; default 128
            :param bedFileFeatures: annotation to display in browser (optional); default None
            :param colorA: color in hex for mA
            :param colorC: color in hex for mCG
            :param dotsize: size of points; default 4
            :param static: produce pdf if True, produe html if False; default False
    Return:
            plot of single molecules within the region of interest
    """

    w = Region(window)

    all_data = []
    aggregate_counts = []
    for f, n in zip(fileNames, sampleNames):
        parse_bam(f, n, basemod=basemod, region=w)
        all_data.append(
            pd.read_sql(
                "SELECT * from methylationByBase",
                sqlite3.connect(f + "_" + n + ".db"),
            )
        )
        aggregate_counts.append(
            pd.read_sql(
                "SELECT * from methylationAggregate",
                sqlite3.connect(f + "_" + n + ".db"),
            )
        )

    meth_browser(
        all_data=all_data,
        aggregate_counts=aggregate_counts,
        basemod=basemod,
        window=Region(window),
        sampleNames=sampleNames,
        outDir=outDir,
        bed=bedFileFeatures,
        smooth=smooth,
        min_periods=min_periods,
        dotsize=dotsize,
        static=static,
        threshA=threshA,
        threshC=threshC,
        colorA=colorA,
        colorC=colorC,
    )


def create_subplots(num_methrows, names=None, annotation=True):
    """
    Prepare the panels (rows * 1 column) for the subplots.
    One row for each dataset, taking 90%/len(datasets) for heights
    if annotation is True (bed) then add a row with height 10%
    """
    return plotly.subplots.make_subplots(
        rows=num_methrows + annotation,
        cols=1,
        shared_xaxes=True,
        specs=[[{}] for i in range(num_methrows + annotation)],
        print_grid=False,
        subplot_titles=names,
        vertical_spacing=0.1 if num_methrows < 10 else 0.01,
        row_heights=[0.9 / num_methrows] * num_methrows + [0.1] * annotation,
    )


def create_output(fig, outfile, window, static, outDir):
    """
    write output pdf or html
    """
    if static:
        outfile = outDir + "/" + f"methylation_browser_{window.string}.pdf"
        fig.write_image(outfile)  # scale=10
        # pio.write_image(fig, outfile, format='pdf', scale=10)
    if not static:
        outfile = outDir + "/" + f"methylation_browser_{window.string}.html"
        with open(outfile, "w+") as output:
            output.write(
                plotly.offline.plot(
                    fig,
                    output_type="div",
                    show_link=False,
                    include_plotlyjs="cdn",
                )
            )


def methylation(
    all_data,
    sampleNames,
    colorA=COLOR_A,
    colorC=COLOR_C,
    dotsize=4,
    threshA=DEFAULT_THRESH_A,
    threshC=DEFAULT_THRESH_C,
):
    """
    Plot methylation traces
    """
    traces = []
    names = []
    for m, n in zip(all_data, sampleNames):
        traces.append(
            make_per_read_meth_traces_phred(
                table=m,
                colorA=colorA,
                colorC=colorC,
                dotsize=dotsize,
                threshA=threshA,
                threshC=threshC,
            )
        )
        names.append(n)
    return DataTraces(traces=traces, names=names)


def make_per_read_meth_traces_phred(
    table,
    colorA,
    colorC,
    max_cov=1000,
    dotsize=4,
    threshA=DEFAULT_THRESH_A,
    threshC=DEFAULT_THRESH_C,
):
    """Make traces for each read"""
    minmax_table = find_min_and_max_pos_per_read(table)
    df_heights = assign_y_height_per_read(minmax_table, max_coverage=max_cov)
    table = pd.merge(table, df_heights, left_on="read_name", right_on="read")
    traces = []
    hidden = 0
    for read in table["read_name"].unique():
        # strand = table.loc[table["read_name"] == read, "strand"].values[0]
        try:
            traces.append(
                make_per_read_line_trace(
                    read_range=minmax_table.loc[read],
                    y_pos=df_heights.loc[read, "height"],
                    # strand=strand,
                )
            )
        except KeyError:
            hidden += 1
            continue
    if hidden:
        sys.stderr.write(
            f"Warning: hiding {hidden} reads because coverage above {max_cov}x.\n"
        )
    read_table_mC = table[table["mod"].str.contains("C")]
    read_table_mA = table[table["mod"].str.contains("A")]
    cmapA = ["white", colorA]
    cmapC = ["white", colorC]
    if read_table_mC is not None:
        traces.append(
            make_per_position_phred_scatter(
                read_table=read_table_mC[read_table_mC["prob"] > threshC],
                mod="mC",
                dotsize=dotsize,
                colorscale=cmapC,
                offset=0.05,
            )
        )
    if read_table_mA is not None:
        traces.append(
            make_per_position_phred_scatter(
                read_table=read_table_mA[read_table_mA["prob"] > threshA],
                mod="mA",
                dotsize=dotsize,
                colorscale=cmapA,
                offset=0.15,
            )
        )
    return traces


def make_per_position_phred_scatter(
    read_table, mod, dotsize=4, colorscale="Reds", offset=0
):
    """Make scatter plot per modified base per read"""
    return go.Scatter(
        x=read_table["pos"],
        y=read_table["height"],
        mode="markers",
        showlegend=False,
        text=round(read_table["prob"] / 255, 2),
        hoverinfo="text",
        marker=dict(
            size=dotsize,
            color=read_table["prob"],
            colorscale=colorscale,
            colorbar=dict(
                title=mod + " probability",
                titleside="right",
                tickvals=[read_table["prob"].min(), read_table["prob"].max()],
                ticktext=[
                    str(round(read_table["prob"].min() / 255, 2)),
                    str(round(read_table["prob"].max() / 255, 3)),
                ],
                ticks="outside",
                x=offset + 1,
            ),
        ),
    )


def find_min_and_max_pos_per_read(table):
    """Return a table with for every read the minimum and maximum position"""
    mm_table = (
        table.loc[:, ["read_name", "pos"]]
        .groupby("read_name")
        .min()
        .join(
            table.loc[:, ["read_name", "pos"]].groupby("read_name").max(),
            lsuffix="min",
            rsuffix="max",
        )
    )
    return mm_table


def assign_y_height_per_read(df, max_coverage=1000):
    """Assign height of the read in the per read traces
    Gets a dataframe of read_name, posmin and posmax.
    Sorting by position.
    Determines optimal height (y coordinate) for this read
    Returns a dictionary mapping read_name to y_coord
    """
    dfs = df.sort_values(by=["posmin", "posmax"], ascending=[True, False])
    heights = [[] for i in range(max_coverage)]
    y_pos = dict()
    for read in dfs.itertuples():
        for y, layer in enumerate(heights, start=1):
            if len(layer) == 0:
                layer.append(read.posmax)
                y_pos[read.Index] = y
                break
            if read.posmin > layer[-1]:
                layer.append(read.posmax)
                y_pos[read.Index] = y
                break
    return pd.DataFrame(
        {"read": list(y_pos.keys()), "height": list(y_pos.values())}
    ).set_index("read")


def make_per_read_line_trace(read_range, y_pos):  # , strand):
    """
    Make a grey line trace for a single read
    """
    return go.Scatter(
        x=[read_range["posmin"], read_range["posmax"]],
        y=[y_pos, y_pos],
        mode="lines",
        line=dict(width=1, color="lightgrey"),
        showlegend=False,
    )


def meth_browser(
    all_data,
    aggregate_counts,
    basemod,
    window,
    sampleNames,
    outDir,
    smooth,
    min_periods,
    bed=False,
    outfile=None,
    dotsize=4,
    static=False,
    threshA=DEFAULT_THRESH_A,
    threshC=DEFAULT_THRESH_C,
    colorA=COLOR_A,
    colorC=COLOR_C,
):
    """
    meth_data is a list of methylationByBase tables as dataframes
    all_dict is a list of methylationAggregate tables as dataframes
    annotation is optional and is a bed file
     then show one line per sample and one for the annotation, with methrows = number of datasets
    the trace to be used for annotation is thus always num_methrows + 1
    """
    meth_traces = methylation(
        all_data,
        sampleNames,
        colorA=colorA,
        colorC=colorC,
        dotsize=dotsize,
        threshA=threshA,
        threshC=threshC,
    )

    num_methrows = len(all_data)
    annot_row = num_methrows + 1
    annot_axis = f"yaxis{annot_row}"
    fig = create_subplots(
        num_methrows, names=meth_traces.names, annotation=bool(bed)
    )
    # for y, (sample_traces, sample_type) in enumerate(meth_traces, start=1):
    for y, sample_traces in enumerate(meth_traces, start=1):
        for meth_trace in sample_traces:
            fig.add_trace(trace=meth_trace, row=y, col=1)
        fig["layout"][f"yaxis{y}"].update(title="Reads")
    if bed:
        for annot_trace in bed_annotation(bed, window):
            fig.add_trace(trace=annot_trace, row=annot_row, col=1)
        y_max = -2
    if bed:
        fig["layout"][annot_axis].update(
            range=[-2, y_max + 1],
            showgrid=False,
            zeroline=False,
            showline=False,
            ticks="",
            showticklabels=False,
        )
    fig["layout"]["xaxis"].update(
        tickformat="g",
        separatethousands=True,
        # showticklabels=True,
        range=[window.begin, window.end],
    )
    fig["layout"].update(
        barmode="overlay",
        title=window.chromosome,
        hovermode="closest",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    if num_methrows > 10:
        for i in fig["layout"]["annotations"]:
            i["font"]["size"] = 10
    create_output(fig, outfile, window, static, outDir)

    i = 0
    for d in aggregate_counts:
        plot_aggregate(
            sampleNames[i],
            d,
            smooth,
            min_periods,
            window,
            basemod,
            outDir,
            colorA,
            colorC,
        )
        i = i + 1


def bed_annotation(bed, window):
    return [
        go.Scatter(
            x=[begin, end],
            y=[-2, -2],
            mode="lines",
            line=dict(width=16, color="grey"),
            text=name,
            hoverinfo="text",
            showlegend=False,
        )
        for (begin, end, name) in parse_bed(bed, window)
    ]


def parse_bed(bed, window):
    gr = pr.read_bed(bed)[window.chromosome, window.begin : window.end]
    df = gr.unstrand().df
    df = df.drop(columns=["Chromosome", "Score", "Strand"], errors="ignore")
    if "Name" not in df.columns:
        df["Name"] = "noname"
    df_short = df[df.columns[0:3]]
    return df_short.itertuples(index=False, name=None)


def plot_aggregate(
    sampleName,
    aggregate_counts,
    smooth,
    min_periods,
    window,
    basemod,
    outDir,
    colorA,
    colorC,
):
    """
    plot rolling aggregate of frac methylated
    plot rolling aggregate of total bases
    """

    aggregate_counts["frac"] = (
        aggregate_counts["methylated_bases"] / aggregate_counts["total_bases"]
    )

    # plot aggregate of fraction and of total count coverage
    if "A" in basemod:
        aggregate_A = aggregate_counts[
            aggregate_counts["mod"].str.contains("A")
        ]
        # need to sort first!
        aggregate_A.sort_values(["pos"], inplace=True)
        aggregate_A_rolling = aggregate_A.rolling(
            window=smooth, min_periods=min_periods, center=True, on="pos"
        ).mean()
        plot_aggregate_frac(
            aggregate_A_rolling, sampleName, "A", colorA, outDir
        )
        plot_aggregate_total(
            aggregate_A_rolling, sampleName, "A", colorA, outDir
        )
    if "C" in basemod:
        aggregate_C = aggregate_counts[
            aggregate_counts["mod"].str.contains("C")
        ]
        # need to sort first!
        aggregate_C.sort_values(["pos"], inplace=True)
        aggregate_C_rolling = aggregate_C.rolling(
            window=smooth, min_periods=min_periods, center=True, on="pos"
        ).mean()
        plot_aggregate_frac(
            aggregate_C_rolling, sampleName, "C", colorC, outDir
        )
        plot_aggregate_total(
            aggregate_C_rolling, sampleName, "C", colorC, outDir
        )


def plot_aggregate_frac(aggregate_rolling, sampleName, mod, color, outDir):
    fig = plt.figure()
    sns.lineplot(
        x=aggregate_rolling["pos"],
        y=aggregate_rolling["frac"],
        color=color,
    )
    plt.title(mod)
    plt.ylabel("m" + mod + "/" + mod)
    plt.show()
    fig.savefig(
        outDir + "/" + sampleName + "_" + mod + "_sm_rolling_avg_fraction.pdf"
    )


def plot_aggregate_total(aggregate_rolling, sampleName, mod, color, outDir):
    fig = plt.figure()
    sns.lineplot(
        x=aggregate_rolling["pos"],
        y=aggregate_rolling["total_bases"],
        color=color,
    )
    plt.title(mod)
    plt.ylabel("total " + mod)
    plt.show()
    fig.savefig(
        outDir + "/" + sampleName + "_" + mod + "_sm_rolling_avg_total.pdf"
    )


def main():
    # TODO add argument parsing
    print("main")
