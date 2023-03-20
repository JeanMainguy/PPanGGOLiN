#!/usr/bin/env python3
# coding:utf-8

# default libraries
import logging
import argparse
import time
import os
from itertools import combinations
from collections.abc import Callable
from collections import defaultdict 
from multiprocessing import get_context
from itertools import islice


# installed libraries
from tqdm import tqdm
import networkx as nx

# local libraries
from ppanggolin.genome import Organism, Contig
from ppanggolin.pangenome import Pangenome
from ppanggolin.region import Region
from ppanggolin.formats import check_pangenome_info, write_pangenome, erase_pangenome
from ppanggolin.utils import restricted_float, mk_outdir

def compute_grr(rgp_a_families:set, rgp_b_families:set, mode:Callable) -> float:
    """
    Compute gene repertoire relatedness (GRR) between two rgp.
    mode can be the function min to compute min GRR or max to compute max_grr

    :param rgp_a: rgp A
    :param rgp_b: rgp B
    :param mode: min or max function

    :return : grr value between 0 and 1
    """
    
    max_grr = len((rgp_a_families & rgp_b_families))/mode(len(rgp_a_families), len(rgp_b_families))

    return max_grr

def compute_jaccard_index(rgp_a_families:set, rgp_b_families:set) -> float:
    """
    Compute jaccard index between two rgp based on their famillies.

    :param rgp_a: rgp A
    :param rgp_b: rgp B

    :return : jaccard index
    """
    
    jaccard_index = len((rgp_a_families & rgp_b_families))/len(rgp_a_families | rgp_b_families)

    return jaccard_index


def get_rgp_info_dict(regions:list, spots:set) -> nx.Graph :
    """

    """

    region_attributes = {}
    for region in regions:

        region_info = {"contig":region.contig.name,
                       'organism':region.organism.name,
                        "name":region.name,
                        "genes_count":len(region.genes), # "length":region.stop_gene - region.start_gene +1, 
                        "is_contig_border":region.is_contig_border, 
                        "is_whole_contig":region.is_whole_contig}
        
        region_info['famillies'] =';'.join([str(f.ID)  for f in region.families])
        region_info['families_count'] = len(region.families)

        region_attributes[region.name] = region_info

    # add spot info to rgp info
    for spot in spots:
        for region in spot.regions:
            region_attributes[region.name]['spot_id'] = spot.ID

    return region_attributes


def add_identical_rgps(rgp_graph, uniq_rgps):
    """
    """
    
    for rgp, identical_rgps in uniq_rgps.items():
        # rgp_graph.add_edges_from(list((rgp, identical_rgp, edge_data) for identical_rgp in identical_rgps),  label="identical_rgp")
        for identical_rgp in identical_rgps:
            rgp_graph.add_edge(rgp.name, identical_rgp.name, max_grr=1.0, min_grr=1.0, jaccard_index=1.0, identical=True)
            rgp_graph.add_node(identical_rgp.name, identical=True)


    

def dereplicate_rgp(rgps: list, disable_bar=False) -> dict: 
    """
    Dereplicate RGPs.

    :params rgps:
    :return : dict with uniq RGP as key and set of identical rgps as value  
    """
    logging.info(f'Dereplicating {len(rgps)} RGPs')
    families_to_rgps = defaultdict(set)

    for rgp in tqdm(rgps, total=len(rgps), unit="RGP", disable=disable_bar):
        families_to_rgps[tuple(rgp.families)].add(rgp)

    uniq_rgps = {}
    for _, rgps in families_to_rgps.items():

        uniq_rgps[rgps.pop()] = rgps

    logging.info(f'{len(uniq_rgps)} uniq RGPs')
    return uniq_rgps

def compute_rgp_metric(pairs_of_rgps):
    """
    """
    pairs_of_rgps_metrics = []
    for (rgp_a, rgp_a_fam), (rgp_b, rgp_b_fam) in pairs_of_rgps:
        # compute metrics between 2 rgp if they share at least one familly
        if rgp_a_fam & rgp_b_fam:
            edge_metrics = {}
            edge_metrics['min_grr'] = compute_grr(rgp_a_fam, rgp_b_fam, min)
            edge_metrics['max_grr']  = compute_grr(rgp_a_fam, rgp_b_fam, max)
            edge_metrics['jaccard_index']  = compute_jaccard_index(rgp_a_fam, rgp_b_fam)

            pairs_of_rgps_metrics.append((rgp_a, rgp_b, edge_metrics))

    return pairs_of_rgps_metrics

def simplify_rgp_object(rgp):
    return rgp.name, {f.ID for f in rgp.families}


def make_chunks(iterable, size):
    """
    """

    i = iter(iterable)
    piece = [(simplify_rgp_object(rgp1),simplify_rgp_object(rgp2)) for rgp1, rgp2 in islice(i, size)]
    while piece:
        yield piece
        piece =  [(simplify_rgp_object(rgp1),simplify_rgp_object(rgp2)) for rgp1, rgp2 in islice(i, size)]

def cluster_rgp(pangenome, output, grr_cutoff, cpu, disable_bar):
    """
    Main function to cluster regions of genomic plasticity based on their GRR

    :param pangenome: pangenome object
    :param output: Allow to force write on Pangenome file
    :param disable_bar: Disable progress bar
    """

    # check statuses and load info
    check_pangenome_info(pangenome, need_families=True, need_annotations=True,
                        disable_bar=disable_bar, need_rgp=True, need_spots=True)

    grr_graph = nx.Graph()

    # add all rgp as node
    uniq_rgps = dereplicate_rgp(pangenome.regions)

    grr_graph.add_nodes_from((rgp.name for rgp in uniq_rgps))

    # compute grr for all possible pair of rgp
    rgp_count = len(uniq_rgps)
    pairs_count = int((rgp_count**2 - rgp_count)/2)
    logging.info(f'Computing GRR metric for {pairs_count:,} pairs of RGP using {cpu} cpus...')
    
    rgp_pairs = combinations(uniq_rgps, 2)
    chunk_size = int(pairs_count/(cpu*10)) +1
    print('CHUNKS ', cpu*10, "of ", chunk_size) 
    chunks_of_rgp_pairs = make_chunks(rgp_pairs, chunk_size)

    # for rgp_a, rgp_b in tqdm(combinations(uniq_rgps, 2), total=pairs_count, unit="RGP pairs", disable=disable_bar) :
    with get_context('fork').Pool(processes=cpu) as p:
        for pairs_of_rgps_metrics in tqdm(p.imap_unordered(compute_rgp_metric, chunks_of_rgp_pairs), unit=f"pairs of rgps", unit_scale=round(pairs_count/(cpu*10)),
                             total=cpu*10, disable=disable_bar):
            grr_graph.add_edges_from(pairs_of_rgps_metrics)

        p.close()
        p.join()
    

    # cluster rgp based on grr
    logging.info(f"Louvain_communities clustering of RGP.")
    min_grr_partitions = nx.algorithms.community.louvain_communities(grr_graph, weight='min_grr')
    max_grr_partitions = nx.algorithms.community.louvain_communities(grr_graph, weight='max_grr')
    jaccard_partitions = nx.algorithms.community.louvain_communities(grr_graph, weight='jaccard_index')
    
    # Add partition index in node attributes
    for i, part in enumerate(min_grr_partitions):
        for node in part:
            grr_graph.add_node(node, min_grr_cluster=f'cluster_{i}')

    for i, part in enumerate(max_grr_partitions):
        for node in part:
            grr_graph.add_node(node, max_grr_cluster=f'cluster_{i}')
            
    for i, part in enumerate(jaccard_partitions):
        for node in part:
            grr_graph.add_node(node, jaccard_index_cluster=f'cluster_{i}')

    logging.info(f"Graph has {len(min_grr_partitions)} clusters using min_grr")
    logging.info(f"Graph has {len(max_grr_partitions)} clusters using max_grr")
    logging.info(f"Graph has {len(max_grr_partitions)} clusters using jaccard index")

    add_identical_rgps(grr_graph, uniq_rgps)
    
    # add some attribute to the graph nodes.
    region_infos = get_rgp_info_dict(pangenome.regions, pangenome.spots)
    nx.set_node_attributes(grr_graph, region_infos)
    
    # writting graph in gexf format
    logging.info(f"Writting graph in gexf and graphml format.")
    nx.readwrite.gexf.write_gexf(grr_graph, output + "/grrGraph.gexf")
    nx.readwrite.graphml.write_graphml(grr_graph, output + "/grrGraph.graphml")

def launch(args: argparse.Namespace):
    """
    Command launcher

    :param args: All arguments provide by user
    """
    pangenome = Pangenome()
    
    mk_outdir(args.output, args.force)

    pangenome.add_file(args.pangenome)

    cluster_rgp(pangenome, args.output, args.grr_cutoff, args.cpu, args.disable_prog_bar)



def subparser(sub_parser: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """
    Subparser to launch PPanGGOLiN in Command line

    :param sub_parser : sub_parser for cluster_rgp command

    :return : parser arguments for cluster_rgp command
    """
    parser = sub_parser.add_parser("rgp_cluster", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser_cluster_rgp(parser)
    return parser


def parser_cluster_rgp(parser: argparse.ArgumentParser):
    """
    Parser for specific argument of rgp command

    :param parser: parser for cluster_rgp argument
    """
    required = parser.add_argument_group(title="Required arguments",
                                         description="One of the following arguments is required :")
    required.add_argument('-p', '--pangenome', required=True, type=str, help="The pangenome .h5 file")

    optional = parser.add_argument_group(title="Optional arguments")

    optional.add_argument('--grr_cutoff', required=False, type=restricted_float, default=0.8,
                          help="Gene repertoire relatedness score cutoff used in the rgp clustering")
    
    # optional.add_argument("-c", "--cpu", required=False, default=1, type=int, help="Number of available cpus")

    optional.add_argument('-o', '--output', required=False, type=str,
                          default="ppanggolin_output" + time.strftime("_DATE%Y-%m-%d_HOUR%H.%M.%S",
                                                                      time.localtime()) + "_PID" + str(os.getpid()),
                          help="Output directory")