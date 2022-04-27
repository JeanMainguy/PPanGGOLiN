#!/usr/bin/env python3
# coding:utf-8

# default libraries
import argparse
from collections import Counter
import logging
import random
import tempfile
import time
from multiprocessing import get_context
import os
import warnings

# installed libraries
from tqdm import tqdm
import gmpy2
import numpy
from pandas import Series, read_csv
import plotly.offline as out_plotly
import plotly.graph_objs as go
import scipy.optimize as optimization

# local libraries
from ppanggolin.pangenome import Pangenome
from ppanggolin.utils import mk_outdir
from ppanggolin.formats import check_pangenome_info
import ppanggolin.nem.partition as ppp

# import this way to use the global variable pan defined in ppanggolin.nem.partition

samples = []


def raref_nem(index, tmpdir, beta, sm_degree, free_dispersion, chunk_size, k, krange, seed):
    samp = samples[index]
    currtmpdir = tmpdir + "/" + str(index) + "/"
    if k < 3:
        k = ppp.evaluate_nb_partitions(samp, sm_degree, free_dispersion, chunk_size, krange, 0.05, False, 1,
                                       tmpdir + "/" + str(index) + "_eval", seed, None)

    if len(samp) <= chunk_size:  # all good, just write stuff.
        edges_weight, nb_fam = ppp.write_nem_input_files(tmpdir=currtmpdir, organisms=set(samp),
                                                         sm_degree=sm_degree)
        cpt_partition = ppp.run_partitioning(currtmpdir, len(samp), beta * (nb_fam / edges_weight), free_dispersion,
                                             kval=k, seed=seed, init="param_file")[0]
    else:  # going to need multiple partitioning for this sample...
        families = set()
        cpt_partition = {}
        validated = set()
        cpt = 0

        def validate_family(result):
            for node, nem_class in result[0].items():
                cpt_partition[node][nem_class[0]] += 1
                sum_partitioning = sum(cpt_partition[node].values())
                if (sum_partitioning > len(samp) / chunk_size and max(
                        cpt_partition[node].values()) >= sum_partitioning * 0.5) or (sum_partitioning > len(samp)):
                    if node not in validated:
                        if max(cpt_partition[node].values()) < sum_partitioning * 0.5:
                            cpt_partition[node]["U"] = len(samp)
                        validated.add(node)

        for fam in ppp.pan.gene_families:
            if not samp.isdisjoint(fam.organisms):  # otherwise, useless to keep track of
                families.add(fam)
                cpt_partition[fam.name] = {"P": 0, "S": 0, "C": 0, "U": 0}

        org_nb_sample = Counter()
        for org in samp:
            org_nb_sample[org] = 0
        condition = len(samp) / chunk_size

        while len(validated) < len(families):
            org_samples = []

            while not all(val >= condition for val in org_nb_sample.values()):
                # each family must be tested at least len(select_organisms)/chunk_size times.
                shuffled_orgs = list(samp)  # copy select_organisms
                random.shuffle(shuffled_orgs)  # shuffle the copied list
                while len(shuffled_orgs) > chunk_size:
                    org_samples.append(set(shuffled_orgs[:chunk_size]))
                    for org in org_samples[-1]:
                        org_nb_sample[org] += 1
                    shuffled_orgs = shuffled_orgs[chunk_size:]
            # making arguments for all samples:
            for samp in org_samples:
                edges_weight, nb_fam = ppp.write_nem_input_files(currtmpdir + "/" + str(cpt) + "/", samp,
                                                                 sm_degree=sm_degree)
                validate_family(
                    ppp.run_partitioning(currtmpdir + "/" + str(cpt) + "/", len(samp), beta * (nb_fam / edges_weight),
                                         free_dispersion, kval=k, seed=seed, init="param_file"))
                cpt += 1
    if len(cpt_partition) == 0:
        counts = {"persistent": "NA", "shell": "NA", "cloud": "NA", "undefined": "NA", "K": k}
    else:
        counts = {"persistent": 0, "shell": 0, "cloud": 0, "undefined": 0, "K": k}

        for val in cpt_partition.values():
            if isinstance(val, str):
                part = val
            else:
                part = max(val, key=val.get)
            if part.startswith("P"):
                counts["persistent"] += 1
            elif part.startswith("C"):
                counts["cloud"] += 1
            elif part.startswith("S"):
                counts["shell"] += 1
            else:
                counts["undefined"] += 1
    return counts, index


def launch_raref_nem(args):
    return raref_nem(*args)


def draw_curve(output, max_sampling, data):
    logging.getLogger().info("Drawing the rarefaction curve ...")
    raref_name = output + "/rarefaction.csv"
    raref = open(raref_name, "w")
    raref.write(",".join(
        ["nb_org", "persistent", "shell", "cloud", "undefined", "exact_core", "exact_accessory", "soft_core",
         "soft_accessory", "pan", "K"]) + "\n")
    for part in data:
        raref.write(",".join(map(str,
                                 [part["nborgs"], part["persistent"], part["shell"], part["cloud"], part["undefined"],
                                  part["exact_core"], part["exact_accessory"], part["soft_core"],
                                  part["soft_accessory"], part["exact_core"] + part["exact_accessory"],
                                  part["K"]])) + "\n")
    raref.close()

    def heap_law(n, p_kappa, p_gamma):
        return p_kappa * n ** p_gamma

    def poly_area(p_x, p_y):
        return 0.5 * numpy.abs(numpy.dot(p_x, numpy.roll(p_y, 1)) - numpy.dot(p_y, numpy.roll(p_x, 1)))

    annotations = []
    traces = []
    data_raref = read_csv(raref_name, index_col=False)
    params_file = open(output + "/rarefaction_parameters" + ".csv", "w")
    params_file.write("partition,kappa,gamma,kappa_std_error,gamma_std_error,IQR_area\n")
    for partition in ["persistent", "shell", "cloud", "undefined", "exact_core", "exact_accessory", "soft_core",
                      "soft_accessory", "pan"]:
        percentiles_75 = Series({i: numpy.nanpercentile(data_raref[data_raref["nb_org"] == i][partition], 75) for i in
                                 range(1, max_sampling + 1)}).dropna()
        percentiles_25 = Series({i: numpy.nanpercentile(data_raref[data_raref["nb_org"] == i][partition], 25) for i in
                                 range(1, max_sampling + 1)}).dropna()
        mins = Series({i: numpy.min(data_raref[data_raref["nb_org"] == i][partition]) for i in
                       range(1, max_sampling + 1)}).dropna()
        maxs = Series({i: numpy.max(data_raref[data_raref["nb_org"] == i][partition]) for i in
                       range(1, max_sampling + 1)}).dropna()
        medians = Series({i: numpy.median(data_raref[data_raref["nb_org"] == i][partition]) for i in
                          range(1, max_sampling + 1)}).dropna()
        means = Series({i: numpy.mean(data_raref[data_raref["nb_org"] == i][partition]) for i in
                        range(1, max_sampling + 1)}).dropna()
        initial_kappa_gamma = numpy.array([0.0, 0.0])
        x = percentiles_25.index.tolist()
        x += list(reversed(percentiles_25.index.tolist()))
        area_iqr = poly_area(x, percentiles_25.tolist() + percentiles_75.tolist())
        nb_org_min_fitting = 15
        colors = {"pan": "black", "exact_accessory": "#EB37ED", "exact_core": "#FF2828", "soft_core": "#c7c938",
                  "soft_accessory": "#996633", "shell": "#00D860", "persistent": "#F7A507", "cloud": "#79DEFF",
                  "undefined": "#828282"}
        try:
            all_values = data_raref[data_raref["nb_org"] > nb_org_min_fitting][partition].dropna()
            res = optimization.curve_fit(heap_law, data_raref.loc[all_values.index]["nb_org"], all_values,
                                         initial_kappa_gamma)
            kappa, gamma = res[0]
            error_k, error_g = numpy.sqrt(numpy.diag(res[1]))  # to calculate the fitting error.
            # The variance of parameters are the diagonal elements of the variance-co variance matrix,
            # and the standard error is the square root of it. source :
            # https://stackoverflow.com/questions/25234996/getting-standard-error-associated-with-parameter-estimates-from-scipy-optimize-c
            if numpy.isinf(error_k) and numpy.isinf(error_g):
                params_file.write(",".join([partition, "NA", "NA", "NA", "NA", str(area_iqr)]) + "\n")
            else:
                params_file.write(
                    ",".join([partition, str(kappa), str(gamma), str(error_k), str(error_g), str(area_iqr)]) + "\n")
                regression = numpy.apply_along_axis(heap_law, 0, range(nb_org_min_fitting + 1, max_sampling + 1), kappa,
                                                    gamma)
                regression_sd_top = numpy.apply_along_axis(heap_law, 0, range(nb_org_min_fitting + 1, max_sampling + 1),
                                                           kappa - error_k, gamma + error_g)
                regression_sd_bottom = numpy.apply_along_axis(heap_law, 0,
                                                              range(nb_org_min_fitting + 1, max_sampling + 1),
                                                              kappa + error_k, gamma - error_g)
                traces.append(go.Scatter(x=list(range(nb_org_min_fitting + 1, max_sampling + 1)),
                                         y=regression,
                                         name=partition + ": Heaps' law",
                                         line=dict(color=colors[partition],
                                                   width=4,
                                                   dash='dash'),
                                         visible="legendonly" if partition == "undefined" else True))
                traces.append(go.Scatter(x=list(range(nb_org_min_fitting + 1, max_sampling + 1)),
                                         y=regression_sd_top,
                                         name=partition + ": Heaps' law error +",
                                         line=dict(color=colors[partition],
                                                   width=1,
                                                   dash='dash'),
                                         visible="legendonly" if partition == "undefined" else True))
                traces.append(go.Scatter(x=list(range(nb_org_min_fitting + 1, max_sampling + 1)),
                                         y=regression_sd_bottom,
                                         name=partition + ": Heaps' law error -",
                                         line=dict(color=colors[partition],
                                                   width=1,
                                                   dash='dash'),
                                         visible="legendonly" if partition == "undefined" else True))
                annotations.append(dict(x=max_sampling,
                                        y=heap_law(max_sampling, kappa, gamma),
                                        ay=0,
                                        ax=50,
                                        text="F=" + str(round(kappa, 0)) + "N" + "<sup>" + str(
                                            round(gamma, 5)) + "</sup><br>IQRarea=" + str(round(area_iqr, 2)),
                                        showarrow=True,
                                        arrowhead=7,
                                        font=dict(size=10, color='white'),
                                        align='center',
                                        arrowcolor=colors[partition],
                                        bordercolor='#c7c7c7',
                                        borderwidth=2,
                                        borderpad=4,
                                        bgcolor=colors[partition],
                                        opacity=0.8))
        except (TypeError, RuntimeError, ValueError):  # if fitting doesn't work
            params_file.write(",".join([partition, "NA", "NA", "NA", "NA", str(area_iqr)]) + "\n")

        traces.append(go.Scatter(x=medians.index,
                                 y=medians,
                                 name=partition + " : medians",
                                 mode="lines+markers",
                                 error_y=dict(type='data',
                                              symmetric=False,
                                              array=maxs.subtract(medians),
                                              arrayminus=medians.subtract(mins),
                                              visible=True,
                                              color=colors[partition],
                                              thickness=0.5),
                                 line=dict(color=colors[partition],
                                           width=1),
                                 marker=dict(color=colors[partition], symbol=3, size=8, opacity=0.5),
                                 visible="legendonly" if partition == "undefined" else True))
        traces.append(go.Scatter(x=means.index,
                                 y=means,
                                 name=partition + " : means",
                                 mode="markers",
                                 marker=dict(color=colors[partition], symbol=4, size=8, opacity=0.5),
                                 visible="legendonly" if partition == "undefined" else True))
        # up = percentiles_75
        # down = percentiles_25
        # IQR_area = up.append(down[::-1])
        # traces.append(go.Scatter(x=IQR_area.index,
        #                          y=IQR_area,
        #                          name = "IQR",
        #                          fill='toself',
        #                          mode="lines",
        #                          hoveron="points",
        #                          #hovertext=[str(round(e)) for e in half_stds.multiply(2)],
        #                          line=dict(color=COLORS[partition]),
        #                          marker=dict(color = COLORS[partition]),
        #                          visible = "legendonly" if partition == "undefined" else True))
        traces.append(go.Scatter(x=percentiles_75.index,
                                 y=percentiles_75,
                                 name=partition + " : 3rd quartile",
                                 mode="lines",
                                 hoveron="points",
                                 # hovertext=[str(round(e)) for e in half_stds.multiply(2)],
                                 line=dict(color=colors[partition]),
                                 marker=dict(color=colors[partition]),
                                 visible="legendonly" if partition == "undefined" else True))
        traces.append(go.Scatter(x=percentiles_25.index,
                                 y=percentiles_25,
                                 name=partition + " : 1st quartile",
                                 fill='tonexty',
                                 mode="lines",
                                 hoveron="points",
                                 # hovertext=[str(round(e)) for e in half_stds.multiply(2)],
                                 line=dict(color=colors[partition]),
                                 marker=dict(color=colors[partition]),
                                 visible="legendonly" if partition == "undefined" else True))
    layout = go.Layout(title="Rarefaction curve ",
                       titlefont=dict(size=20),
                       xaxis=dict(title='size of genome subsets (N)'),
                       yaxis=dict(title='# of gene families (F)'),
                       annotations=annotations,
                       plot_bgcolor='#ffffff')
    fig = go.Figure(data=traces, layout=layout)
    out_plotly.plot(fig, filename=output + "/rarefaction_curve.html", auto_open=False)
    params_file.close()


def make_rarefaction_curve(pangenome, output, tmpdir, beta=2.5, depth=30, min_sampling=1, max_sampling=100,
                           sm_degree=10, free_dispersion=False, chunk_size=500, k=-1, cpu=1, seed=42, kestimate=False,
                           krange=None, soft_core=0.95, disable_bar=False):
    if krange is None:
        krange = [3, -1]
    ppp.pan = pangenome  # use the global from partition to store the pan, so that it is usable

    try:
        krange[0] = ppp.pan.parameters["partition"]["K"] if krange[0] < 0 else krange[0]
        krange[1] = ppp.pan.parameters["partition"]["K"] if krange[1] < 0 else krange[1]
    except KeyError:
        krange = [3, 20]
    check_pangenome_info(pangenome, need_annotations=True, need_families=True, need_graph=True, disable_bar=disable_bar)

    tmpdir_obj = tempfile.TemporaryDirectory(dir=tmpdir)
    tmpdir = tmpdir_obj.name

    if float(len(pangenome.organisms)) < max_sampling:
        max_sampling = len(pangenome.organisms)
    else:
        max_sampling = int(max_sampling)

    if k < 3 and kestimate is False:  # estimate K once and for all.
        try:
            k = ppp.pan.parameters["partition"]["K"]
            logging.getLogger().info(f"Reuse the number of partitions {k}")
        except KeyError:
            logging.getLogger().info("Estimating the number of partitions...")
            k = ppp.evaluate_nb_partitions(pangenome.organisms, sm_degree, free_dispersion, chunk_size, krange, 0.05,
                                           False, cpu, tmpdir, seed, None)
            logging.getLogger().info(f"The number of partitions has been evaluated at {k}")

    logging.getLogger().info("Extracting samples ...")
    all_samples = []
    for i in range(min_sampling, max_sampling):  # each point
        for _ in range(depth):  # number of samples per points
            all_samples.append(set(random.sample(set(pangenome.organisms), i + 1)))
    logging.getLogger().info(f"Done sampling organisms in the pan, there are {len(all_samples)} samples")
    samp_nb_per_part = []

    logging.getLogger().info("Computing bitarrays for each family...")
    index_org = pangenome.compute_family_bitarrays()
    logging.getLogger().info(
        f"Done computing bitarrays. Comparing them to get exact and soft core stats for {len(all_samples)} samples...")
    bar = tqdm(range(len(all_samples) * len(pangenome.gene_families)), unit="gene family", disable=disable_bar)
    for samp in all_samples:
        # make the sample's organism bitarray.
        samp_bitarray = gmpy2.xmpz()  # pylint: disable=no-member
        for org in samp:
            samp_bitarray[index_org[org]] = 1

        part = Counter()
        part["soft_core"] = 0
        part["exact_core"] = 0
        part["exact_accessory"] = 0
        part["soft_accessory"] = 0
        for fam in pangenome.gene_families:
            nb_common_org = gmpy2.popcount(fam.bitarray & samp_bitarray)  # pylint: disable=no-member
            part["nborgs"] = len(samp)
            if nb_common_org != 0:  # in that case the node 'does not exist'
                if nb_common_org == len(samp):
                    part["exact_core"] += 1
                else:
                    part["exact_accessory"] += 1

                if float(nb_common_org) >= len(samp) * soft_core:
                    part["soft_core"] += 1
                else:
                    part["soft_accessory"] += 1
            bar.update()
        samp_nb_per_part.append(part)
    bar.close()
    # done with frequency of each family for each sample.

    global samples
    samples = all_samples

    args = []
    for index, samp in enumerate(samples):
        args.append((index, tmpdir, beta, sm_degree, free_dispersion, chunk_size, k, krange, seed))

    with get_context('fork').Pool(processes=cpu) as p:
        # launch partitioning
        logging.getLogger().info(" Partitioning all samples...")
        bar = tqdm(range(len(args)), unit="samples partitioned", disable=disable_bar)
        random.shuffle(args)  # shuffling the processing so that the progress bar is closer to reality.
        for result in p.imap_unordered(launch_raref_nem, args):
            samp_nb_per_part[result[1]] = {**result[0], **samp_nb_per_part[result[1]]}
            bar.update()
    bar.close()

    logging.getLogger().info("Done  partitioning everything")
    warnings.filterwarnings("ignore")
    draw_curve(output, max_sampling, samp_nb_per_part)
    warnings.resetwarnings()
    tmpdir_obj.cleanup()
    logging.getLogger().info("Done making the rarefaction curves")


def launch(args):
    """
        main code when launch partition from the command line.
    """
    mk_outdir(args.output, args.force)
    pangenome = Pangenome()
    pangenome.add_file(args.pan)
    make_rarefaction_curve(pangenome=pangenome, output=args.output, tmpdir=args.tmpdir, beta=args.beta,
                           depth=args.depth, min_sampling=args.min, max_sampling=args.max,
                           sm_degree=args.max_degree_smoothing, free_dispersion=args.free_dispersion,
                           chunk_size=args.chunk_size, k=args.nb_of_partitions, cpu=args.cpu, seed=args.seed,
                           kestimate=args.reestimate_K, krange=args.krange, soft_core=args.soft_core,
                           disable_bar=args.disable_prog_bar)


def subparser(sub_parser):
    parser = sub_parser.add_parser("rarefaction", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser_rarefaction(parser)
    return parser


def parser_rarefaction(parser):
    required = parser.add_argument_group(title="Required arguments",
                                         description="One of the following arguments is required :")
    required.add_argument('-p', '--pan', required=True, type=str, help="The pan .h5 file")

    optional = parser.add_argument_group(title="Optional arguments")
    optional.add_argument("-b", "--beta", required=False, default=2.5, type=float,
                          help="beta is the strength of the smoothing using the graph topology during  partitioning. "
                               "0 will deactivate spatial smoothing.")
    optional.add_argument("--depth", required=False, default=30, type=int,
                          help="Number of samplings at each sampling point")
    optional.add_argument("--min", required=False, default=1, type=int, help="Minimum number of organisms in a sample")
    optional.add_argument("--max", required=False, type=float, default=100,
                          help="Maximum number of organisms in a sample (if above the number of provided organisms, "
                               "the provided organisms will be the maximum)")

    optional.add_argument("-ms", "--max_degree_smoothing", required=False, default=10, type=float,
                          help="max. degree of the nodes to be included in the smoothing process.")
    optional.add_argument('-o', '--output', required=False, type=str,
                          default="ppanggolin_output" + time.strftime("_DATE%Y-%m-%d_HOUR%H.%M.%S",
                                                                      time.localtime()) + "_PID" + str(os.getpid()),
                          help="Output directory")
    optional.add_argument("-fd", "--free_dispersion", required=False, default=False, action="store_true",
                          help="use if the dispersion around the centroid vector of each partition during must be free."
                               " It will be the same for all organisms by default.")
    optional.add_argument("-ck", "--chunk_size", required=False, default=500, type=int,
                          help="Size of the chunks when performing partitioning using chunks of organisms. "
                               "Chunk partitioning will be used automatically "
                               "if the number of genomes is above this number.")
    optional.add_argument("-K", "--nb_of_partitions", required=False, default=-1, type=int,
                          help="Number of partitions to use. Must be at least 2. "
                               "By default reuse K if it exists else compute it.")
    optional.add_argument("--reestimate_K", required=False, action="store_true",
                          help=" Will recompute the number of partitions for each sample "
                               "(between the values provided by --krange) (VERY intensive. Can take a long time.)")
    optional.add_argument("-Kmm", "--krange", nargs=2, required=False, type=int, default=[3, -1],
                          help="Range of K values to test when detecting K automatically. "
                               "Default between 3 and the K previously computed "
                               "if there is one, or 20 if there are none.")
    optional.add_argument("--soft_core", required=False, type=float, default=0.95, help="Soft core threshold")
    optional.add_argument("-se", "--seed", type=int, default=42, help="seed used to generate random numbers")


if __name__ == '__main__':
    """To test local change and allow using debugger"""
    from ppanggolin.utils import check_log, set_verbosity_level

    main_parser = argparse.ArgumentParser(
        description="Depicting microbial species diversity via a Partitioned PanGenome Graph Of Linked Neighbors",
        formatter_class=argparse.RawTextHelpFormatter)

    parser_rarefaction(main_parser)
    common = main_parser.add_argument_group(title="Common argument")
    common.add_argument("--verbose", required=False, type=int, default=1, choices=[0, 1, 2],
                        help="Indicate verbose level (0 for warning and errors only, 1 for info, 2 for debug)")
    common.add_argument("--tmpdir", required=False, type=str, default=tempfile.gettempdir(),
                        help="directory for storing temporary files")
    common.add_argument("--log", required=False, type=check_log, default="stdout", help="log output file")
    common.add_argument("-d", "--disable_prog_bar", required=False, action="store_true",
                        help="disables the progress bars")
    common.add_argument("-c", "--cpu", required=False, default=1, type=int, help="Number of available cpus")
    common.add_argument('-f', '--force', action="store_true",
                        help="Force writing in output directory and in pangenome output file.")
    set_verbosity_level(main_parser.parse_args())
    launch(main_parser.parse_args())
