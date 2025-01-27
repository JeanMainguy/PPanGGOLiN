#!/usr/bin/env python3
# coding:utf-8

# default libraries
import argparse
from multiprocessing import get_context
from collections import Counter, defaultdict
import logging
from typing import TextIO
import pkg_resources
from statistics import median, mean, stdev
import os

# local libraries
from ppanggolin.edge import Edge
from ppanggolin.geneFamily import GeneFamily
from ppanggolin.genome import Organism
from ppanggolin.pangenome import Pangenome
from ppanggolin.utils import write_compressed_or_not, mk_outdir, restricted_float
from ppanggolin.formats.readBinaries import check_pangenome_info

# global variable to store the pan
pan = Pangenome()  # TODO change to pan:Pangenome = Pangenome=() ?
needAnnotations = False
needFamilies = False
needGraph = False
needPartitions = False
needSpots = False
needRegions = False
needModules = False
ignore_err = False


def write_json_header(json: TextIO):
    """Write the header of json file to save graph

    :param json: file-like object, compressed or not
    """
    json.write('{"directed": false, "multigraph": false,')
    json.write(' "graph": {')
    json.write(' "organisms": {')
    orgstr = []
    for org in pan.organisms:
        orgstr.append('"' + org.name + '": {')
        contigstr = []
        for contig in org.contigs:
            contigstr.append(f'"{contig.name}": ' + '{"is_circular: ' +
                             ('true' if contig.is_circular else 'false') + '}')
        orgstr[-1] += ', '.join(contigstr) + "}"

    json.write(', '.join(orgstr) + "}")
    # if other things are to be written such as the parameters, write them here
    json.write('},')


def write_json_gene_fam(gene_fam: GeneFamily, json: TextIO):
    """Write the gene families corresponding to node graph in json file

    :param gene_fam: file-like object, compressed or not
    :param json: file-like object, compressed or not
    """
    json.write('{' + f'"id": "{gene_fam.name}", "nb_genes": {len(gene_fam.genes)}, '
                     f'"partition": "{gene_fam.named_partition}", "subpartition": "{gene_fam.partition}"' + '}')
    org_dict = {}
    name_counts = Counter()
    product_counts = Counter()
    length_counts = Counter()
    for gene in gene_fam.genes:
        name_counts[gene.name] += 1
        product_counts[gene.product] += 1
        length_counts[gene.stop - gene.start] += 1
        try:
            org_dict[gene.organism][gene.contig].append(gene)
        except KeyError:
            try:
                org_dict[gene.organism][gene.contig] = [gene]
            except KeyError:
                org_dict[gene.organism] = {gene.contig: [gene]}

    json.write(f', "name": "{name_counts.most_common(1)[0][0]}", "product": "{product_counts.most_common(1)[0][0]}", '
               f'"length": {length_counts.most_common(1)[0][0]}')

    json.write(', "organisms": {')
    orgstr = []
    for org in org_dict:
        orgstr.append('"' + org.name + '": {')
        contigstr = []
        for contig in org_dict[org]:
            contigstr.append('"' + contig.name + '": {')
            genestr = []
            for gene in org_dict[org][contig]:
                identifier = gene.ID if gene.local_identifier == "" else gene.local_identifier
                genestr.append('"' + identifier + '": {' + f'"name": "{gene.name}", "product": "{gene.product}", '
                                                           f'"is_fragment": {"true" if gene.is_fragment else "false"},'
                                                           f' "position": {gene.position}, "strand": "{gene.strand}",'
                                                           f' "end": {gene.stop}, "start": {gene.start}' + '}')
            contigstr[-1] += ", ".join(genestr) + "}"
        orgstr[-1] += ", ".join(contigstr) + "}"
    json.write(", ".join(orgstr) + "}}")


def write_json_nodes(json: TextIO):
    """Write the node graph in json file

    :param json: file-like object, compressed or not
    """
    json.write('"nodes": [')
    fam_list = list(pan.gene_families)
    first_fam = fam_list[0]
    write_json_gene_fam(first_fam, json)
    for geneFam in fam_list[1:]:
        json.write(', ')
        write_json_gene_fam(geneFam, json)
    json.write(']')


def write_json_edge(edge: Edge, json: TextIO):
    """Write the edge graph in json file

    :param edge: file-like object, compressed or not
    :param json: file-like object, compressed or not
    """
    json.write("{")
    json.write(f'"weight": {len(edge.gene_pairs)}, "source": "{edge.source.name}", "target": "{edge.target.name}"')
    json.write(', "organisms": {')
    orgstr = []
    for org in edge.get_org_dict():
        orgstr.append('"' + org.name + '": [')
        genepairstr = []
        for genepair in edge.get_org_dict()[org]:
            genepairstr.append('{"source": "' + genepair[0].ID + '", "target": "' + genepair[
                1].ID + f'", "length": {genepair[0].start - genepair[1].stop}' + '}')
        orgstr[-1] += ', '.join(genepairstr) + ']'
    json.write(', '.join(orgstr) + "}}")


def write_json_edges(json):
    """Write the edge graph in json file

    :param json: file-like object, compressed or not
    """
    json.write(', "links": [')
    edgelist = pan.edges
    write_json_edge(edgelist[0], json)
    for edge in edgelist[1:]:
        json.write(", ")
        write_json_edge(edge, json)
    json.write(']')


def write_json(output: str, compress: bool = False):
    """Writes the graph in a json file format

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info("Writing the json file for the pangenome graph...")
    outname = output + "/pangenomeGraph.json"
    with write_compressed_or_not(outname, compress) as json:
        write_json_header(json)
        write_json_nodes(json)
        write_json_edges(json)
        json.write("}")
    logging.getLogger().info(f"Done writing the json file : '{outname}'")


def write_gexf_header(gexf: TextIO, light: bool = True):
    """Write the header of gexf file to save graph

    :param gexf: file-like object, compressed or not
    :param light: save the light version of the pangenome graph
    """
    index = None
    if not light:
        index = pan.get_org_index()  # has been computed already
    gexf.write('<?xml version="1.1" encoding="UTF-8"?>\n<gexf xmlns:viz="https://www.gexf.net/1.2draft/viz"'
               ' xmlns="https://www.gexf.net/1.2draft" version="1.2">\n')  # TODO update link
    gexf.write('  <graph mode="static" defaultedgetype="undirected">\n')
    gexf.write('    <attributes class="node" mode="static">\n')
    gexf.write('      <attribute id="0" title="nb_genes" type="long" />\n')
    gexf.write('      <attribute id="1" title="name" type="string" />\n')
    gexf.write('      <attribute id="2" title="product" type="string" />\n')
    gexf.write('      <attribute id="3" title="type" type="string" />\n')
    gexf.write('      <attribute id="4" title="partition" type="string" />\n')
    gexf.write('      <attribute id="5" title="subpartition" type="string" />\n')
    gexf.write('      <attribute id="6" title="partition_exact" type="string" />\n')
    gexf.write('      <attribute id="7" title="partition_soft" type="string" />\n')
    gexf.write('      <attribute id="8" title="length_avg" type="double" />\n')
    gexf.write('      <attribute id="9" title="length_med" type="long" />\n')
    gexf.write('      <attribute id="10" title="nb_organisms" type="long" />\n')
    if not light:
        for org, orgIndex in index.items():
            gexf.write(f'      <attribute id="{orgIndex + 12}" title="{org.name}" type="string" />\n')

    gexf.write('    </attributes>\n')
    gexf.write('    <attributes class="edge" mode="static">\n')
    gexf.write('      <attribute id="11" title="nb_genes" type="long" />\n')
    if not light:
        for org, orgIndex in index.items():
            gexf.write(f'      <attribute id="{orgIndex + len(index) + 12}" title="{org.name}" type="long" />\n')
    gexf.write('    </attributes>\n')
    gexf.write('    <meta>\n')
    gexf.write(f'      <creator>PPanGGOLiN {pkg_resources.get_distribution("ppanggolin").version}</creator>\n')
    gexf.write('    </meta>\n')


def write_gexf_nodes(gexf: TextIO, light: bool = True, soft_core: False = 0.95):
    """Write the node of pangenome graph in gexf file

    :param gexf: file-like object, compressed or not
    :param light: save the light version of the pangenome graph
    :param soft_core: Soft core threshold to use
    """
    index = None
    gexf.write('    <nodes>\n')
    colors = {"persistent": 'a="0" b="7" g="165" r="247"', 'shell': 'a="0" b="96" g="216" r="0"',
              'cloud': 'a="0" b="255" g="222" r="121"'}
    if not light:
        index = pan.get_org_index()

    for fam in pan.gene_families:
        name = Counter()
        product = Counter()
        gtype = Counter()
        lis = []
        for gene in fam.genes:
            name[gene.name] += 1
            product[gene.product.replace('&', 'and')] += 1
            gtype[gene.type] += 1
            lis.append(gene.stop - gene.start)

        gexf.write(f'      <node id="{fam.ID}" label="{fam.name}">\n')
        gexf.write(f'        <viz:color {colors[fam.named_partition]} />\n')
        gexf.write(f'        <viz:size value="{len(fam.organisms)}" />\n')
        gexf.write(f'        <attvalues>\n')
        gexf.write(f'          <attvalue for="0" value="{len(fam.genes)}" />\n')
        gexf.write(f'          <attvalue for="1" value="{name.most_common(1)[0][0]}" />\n')
        gexf.write(f'          <attvalue for="2" value="{product.most_common(1)[0][0]}" />\n')
        gexf.write(f'          <attvalue for="3" value="{gtype.most_common(1)[0][0]}" />\n')
        gexf.write(f'          <attvalue for="4" value="{fam.named_partition}" />\n')
        gexf.write(f'          <attvalue for="5" value="{fam.partition}" />\n')
        gexf.write(f'          <attvalue for="6" value="'
                   f'{"exact_accessory" if len(fam.organisms) != len(pan.organisms) else "exact_core"}" />\n')
        gexf.write(f'          <attvalue for="7" value="'
                   f'{"soft_core" if len(fam.organisms) >= (len(pan.organisms) * soft_core) else "soft_accessory"}"'
                   f' />\n')
        gexf.write(f'          <attvalue for="8" value="{round(sum(lis) / len(lis), 2)}" />\n')
        gexf.write(f'          <attvalue for="9" value="{int(median(lis))}" />\n')
        gexf.write(f'          <attvalue for="10" value="{len(fam.organisms)}" />\n')
        if not light:
            for org, genes in fam.get_org_dict().items():
                gexf.write(
                    f'          <attvalue for="'
                    f'{index[org] + 12}" '
                    f'value="{"|".join([gene.ID if gene.local_identifier == "" else gene.local_identifier for gene in genes])}" />\n')
        gexf.write(f'        </attvalues>\n')
        gexf.write(f'      </node>\n')
    gexf.write('    </nodes>\n')


def write_gexf_edges(gexf: TextIO, light: bool = True):
    """Write the edge of pangenome graph in gexf file

    :param gexf: file-like object, compressed or not
    :param light: save the light version of the pangenome graph
    """
    gexf.write('    <edges>\n')
    edgeids = 0
    index = pan.get_org_index()

    for edge in pan.edges:
        gexf.write(f'      <edge id="{edgeids}" source="'
                   f'{edge.source.ID}" target="{edge.target.ID}" weight="{len(edge.organisms)}">\n')
        gexf.write(f'        <viz:thickness value="{len(edge.organisms)}" />\n')
        gexf.write('        <attvalues>\n')
        gexf.write(f'          <attribute id="11" value="{len(edge.gene_pairs)}" />\n')
        if not light:
            for org, genes in edge.get_org_dict().items():
                gexf.write(f'          <attvalue for="{index[org] + len(index) + 12}" value="{len(genes)}" />\n')
        gexf.write('        </attvalues>\n')
        gexf.write('      </edge>\n')
        edgeids += 1
    gexf.write('    </edges>\n')


def write_gexf_end(gexf: TextIO):
    """Write the end of gexf file to save pangenome

    :param gexf: file-like object, compressed or not
    """
    gexf.write("  </graph>")
    gexf.write("</gexf>")


def write_gexf(output: str, light: bool = True, compress: bool = False):
    """Write the node of pangenome in gexf file

    :param output: Path to output directory
    :param light: save the light version of the pangenome graph
    :param compress: Compress the file in .gz
    """
    txt = "Writing the "
    txt += "light gexf file for the pangenome graph..." if light else "gexf file for the pangenome graph..."

    logging.getLogger().info(txt)
    outname = output + "/pangenomeGraph"
    outname += "_light" if light else ""
    outname += ".gexf"
    with write_compressed_or_not(outname, compress) as gexf:
        write_gexf_header(gexf, light)
        write_gexf_nodes(gexf, light)
        write_gexf_edges(gexf, light)
        write_gexf_end(gexf)
    logging.getLogger().info(f"Done writing the gexf file : '{outname}'")


def write_matrix(output: str, sep: str = ',', ext: str = 'csv', compress: bool = False, gene_names: bool = False):
    """
    Write a csv file format as used by Roary, among others.
    The alternative gene ID will be the partition, if there is one

    :param sep: Column field separator
    :param ext: file extension
    :param output: Path to output directory
    :param compress: Compress the file in .gz
    :param gene_names: write the genes name if there are saved in  pangenome
    """
    logging.getLogger().info(f"Writing the .{ext} file ...")
    outname = output + "/matrix." + ext
    with write_compressed_or_not(outname, compress) as matrix:

        index_org = {}
        default_dat = []
        for index, org in enumerate(pan.organisms):
            default_dat.append('0')
            index_org[org] = index

        matrix.write(sep.join(['"Gene"',  # 1
                               '"Non-unique Gene name"',  # 2
                               '"Annotation"',  # 3
                               '"No. isolates"',  # 4
                               '"No. sequences"',  # 5
                               '"Avg sequences per isolate"',  # 6
                               '"Accessory Fragment"',  # 7
                               '"Genome Fragment"',  # 8
                               '"Order within Fragment"',  # 9
                               '"Accessory Order with Fragment"',  # 10
                               '"QC"',  # 11
                               '"Min group size nuc"',  # 12
                               '"Max group size nuc"',  # 13
                               '"Avg group size nuc"']  # 14
                              + ['"' + str(org) + '"' for org in pan.organisms]) + "\n")  # 15
        default_genes = ['""'] * len(pan.organisms) if gene_names else ["0"] * len(pan.organisms)
        org_index = pan.get_org_index()  # should just return things
        for fam in pan.gene_families:
            genes = default_genes.copy()
            lis = []
            genenames = Counter()
            product = Counter()
            for org, gene_list in fam.get_org_dict().items():
                genes[org_index[org]] = " ".join(['"' + str(gene) +
                                                  '"' for gene in gene_list]) if gene_names else str(len(gene_list))
                for gene in gene_list:
                    lis.append(gene.stop - gene.start)
                    product[gene.product] += 1
                    genenames[gene.name] += 1

            if fam.partition != "":
                alt = fam.named_partition
            else:
                alt = str(product.most_common(1)[0][0])

            lis = [gene.stop - gene.start for gene in fam.genes]
            matrix.write(sep.join(['"' + fam.name + '"',  # 1
                                   '"' + alt + '"',  # 2
                                   '"' + str(product.most_common(1)[0][0]) + '"',  # 3
                                   '"' + str(len(fam.organisms)) + '"',  # 4
                                   '"' + str(len(fam.genes)) + '"',  # 5
                                   '"' + str(round(len(fam.genes) / len(fam.organisms), 2)) + '"',  # 6
                                   '"NA"',  # 7
                                   '"NA"',  # 8
                                   '""',  # 9
                                   '""',  # 10
                                   '""',  # 11
                                   '"' + str(min(lis)) + '"',  # 12
                                   '"' + str(max(lis)) + '"',  # 13
                                   '"' + str(round(sum(lis) / len(lis), 2)) + '"']  # 14
                                  + genes) + "\n")  # 15
    logging.getLogger().info(f"Done writing the matrix : '{outname}'")


def write_gene_presence_absence(output: str, compress: bool = False):
    """
    Write the gene presence absence matrix

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info(f"Writing the gene presence absence file ...")
    outname = output + "/gene_presence_absence.Rtab"
    with write_compressed_or_not(outname, compress) as matrix:
        index_org = {}
        default_dat = []
        for index, org in enumerate(pan.organisms):
            default_dat.append('0')
            index_org[org] = index

        matrix.write('\t'.join(['Gene'] +  # 14
                               [str(org) for org in pan.organisms]) + "\n")  # 15
        default_genes = ["0"] * len(pan.organisms)
        org_index = pan.get_org_index()  # should just return things
        for fam in pan.gene_families:
            genes = default_genes.copy()
            for org in fam.organisms:
                genes[org_index[org]] = "1"

            matrix.write('\t'.join([fam.name]  # 14
                                   + genes) + "\n")  # 15
    logging.getLogger().info(f"Done writing the gene presence absence file : '{outname}'")


def write_stats(output: str, soft_core: float = 0.95, dup_margin: float = 0.05, compress: bool = False):
    """
    Write pangenome statistics

    :param output: Path to output directory
    :param soft_core: Soft core threshold to use
    :param dup_margin: minimum ratio of organisms in which family must have multiple genes to be considered duplicated
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info("Writing pangenome statistics...")
    logging.getLogger().info("Writing statistics on persistent duplication...")
    single_copy_markers = set()  # could use bitarrays if speed is needed
    with write_compressed_or_not(output + "/mean_persistent_duplication.tsv", compress) as outfile:
        outfile.write(f"#duplication_margin={round(dup_margin, 3)}\n")
        outfile.write("\t".join(["persistent_family", "duplication_ratio", "mean_presence", "is_single_copy_marker"]) +
                      "\n")
        for fam in pan.gene_families:
            if fam.named_partition == "persistent":
                mean_pres = len(fam.genes) / len(fam.organisms)
                nb_multi = 0
                for gene_list in fam.get_org_dict().values():
                    if len(gene_list) > 1:
                        nb_multi += 1
                dup_ratio = nb_multi / len(fam.organisms)
                is_scm = False
                if dup_ratio < dup_margin:
                    is_scm = True
                    single_copy_markers.add(fam)
                outfile.write("\t".join([fam.name,
                                         str(round(dup_ratio, 3)),
                                         str(round(mean_pres, 3)),
                                         str(is_scm)]) + "\n")
    logging.getLogger().info("Done writing stats on persistent duplication")
    logging.getLogger().info("Writing genome per genome statistics (completeness and counts)...")
    soft = set()  # could use bitarrays if speed is needed
    core = set()
    for fam in pan.gene_families:
        if len(fam.organisms) >= pan.number_of_organisms() * soft_core:
            soft.add(fam)
        if len(fam.organisms) == pan.number_of_organisms():
            core.add(fam)

    with write_compressed_or_not(output + "/organisms_statistics.tsv", compress) as outfile:
        outfile.write(f"#soft_core={round(soft_core, 3)}\n")
        outfile.write(f"#duplication_margin={round(dup_margin, 3)}\n")
        outfile.write("\t".join(
            ["organism", "nb_families", "nb_persistent_families", "nb_shell_families", "nb_cloud_families",
             "nb_exact_core", "nb_soft_core", "nb_genes", "nb_persistent_genes", "nb_shell_genes", "nb_cloud_genes",
             "nb_exact_core_genes", "nb_soft_core_genes", "completeness", "nb_single_copy_markers"]) + "\n")

        for org in pan.organisms:
            fams = org.families
            nb_pers = 0
            nb_shell = 0
            nb_cloud = 0
            for fam in fams:
                if fam.named_partition == "persistent":
                    nb_pers += 1
                elif fam.named_partition == "shell":
                    nb_shell += 1
                else:
                    nb_cloud += 1

            nb_gene_pers = 0
            nb_gene_shell = 0
            nb_gene_soft = 0
            nb_gene_cloud = 0
            nb_gene_core = 0
            for gene in org.genes:
                if gene.family.named_partition == "persistent":
                    nb_gene_pers += 1
                elif gene.family.named_partition == "shell":
                    nb_gene_shell += 1
                else:
                    nb_gene_cloud += 1
                if gene.family in soft:
                    nb_gene_soft += 1
                    if gene.family in core:
                        nb_gene_core += 1
            completeness = "NA"
            if len(single_copy_markers) > 0:
                completeness = round((len(fams & single_copy_markers) / len(single_copy_markers)) * 100, 2)
            outfile.write("\t".join(map(str, [org.name,
                                              len(fams),
                                              nb_pers,
                                              nb_shell,
                                              nb_cloud,
                                              len(core & fams),
                                              len(soft & fams),
                                              org.number_of_genes(),
                                              nb_gene_pers,
                                              nb_gene_shell,
                                              nb_gene_cloud,
                                              nb_gene_core,
                                              nb_gene_soft,
                                              completeness,
                                              len(fams & single_copy_markers)])) + "\n")

    logging.getLogger().info("Done writing genome per genome statistics")


def write_org_file(org: Organism, output: str, compress: bool = False):
    """
    Write the projection of pangenome for one organism

    :param org: Projected organism
    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    with write_compressed_or_not(output + "/" + org.name + ".tsv", compress) as outfile:
        header = ["gene", "contig", "start", "stop", "strand", "family", "nb_copy_in_org",
                  "partition", "persistent_neighbors", "shell_neighbors", "cloud_neighbors"]
        if needRegions:
            header.append("RGPs")
        if needSpots:
            header.append("Spots")
        if needModules:
            header.append("Modules")
        outfile.write("\t".join(header) + "\n")
        for contig in org.contigs:
            for gene in contig.genes:
                nb_pers = 0
                nb_shell = 0
                nb_cloud = 0
                modules = None
                rgp = None
                spot = None
                for neighbor in gene.family.neighbors:
                    if neighbor.named_partition == "persistent":
                        nb_pers += 1
                    elif neighbor.named_partition == "shell":
                        nb_shell += 1
                    else:
                        nb_cloud += 1
                row = [gene.ID if gene.local_identifier == "" else gene.local_identifier,
                       contig.name, gene.start, gene.stop, gene.strand, gene.family.name,
                       len(gene.family.get_genes_per_org(org)), gene.family.named_partition,
                       nb_pers, nb_shell, nb_cloud]
                if needRegions:
                    if len(gene.RGP) > 0:
                        rgp = ','.join([str(region.name) for region in gene.RGP])
                    row.append(rgp)
                if needSpots:
                    if len(gene.family.spot) > 0:
                        spot = ','.join([str(s.ID) for s in gene.family.spot])
                    row.append(spot)
                if needModules:
                    if len(gene.family.modules) > 0:
                        modules = ','.join(["module_" + str(module.ID) for module in gene.family.modules])
                    row.append(modules)
                outfile.write("\t".join(map(str, row)) + "\n")


def write_projections(output: str, compress: bool = False):
    """
    Write the projection of pangenome for all organisms

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info("Writing the projection files...")
    outdir = output + "/projection"
    if not os.path.exists(outdir):
        os.makedirs(outdir)
    for org in pan.organisms:
        write_org_file(org, outdir, compress)
    logging.getLogger().info("Done writing the projection files")


def write_parts(output: str, soft_core: float = 0.95):
    """
    Write the list of gene families for each partition

    :param output: Path to output directory
    :param soft_core: Soft core threshold to use
    """
    logging.getLogger().info("Writing the list of gene families for each partition ...")
    if not os.path.exists(output + "/partitions"):
        os.makedirs(output + "/partitions")
    part_sets = defaultdict(set)
    # initializing key, value pairs so that files exist even if they are empty
    for neededKey in ["undefined", "soft_core", "exact_core", "exact_accessory", "soft_accessory", "persistent",
                      "shell", "cloud"]:
        part_sets[neededKey] = set()
    for fam in pan.gene_families:
        part_sets[fam.named_partition].add(fam.name)
        if fam.partition.startswith("S"):
            part_sets[fam.partition].add(fam.name)
        if len(fam.organisms) >= len(pan.organisms) * soft_core:
            part_sets["soft_core"].add(fam.name)
            if len(fam.organisms) == len(pan.organisms):
                part_sets["exact_core"].add(fam.name)
            else:
                part_sets["exact_accessory"].add(fam.name)
        else:
            part_sets["soft_accessory"].add(fam.name)
            part_sets["exact_accessory"].add(fam.name)

    for key, val in part_sets.items():
        curr_key_file = open(output + "/partitions/" + key + ".txt", "w")
        if len(val) > 0:
            curr_key_file.write('\n'.join(val) + "\n")
        curr_key_file.close()
    logging.getLogger().info("Done writing the list of gene families for each partition")


def write_gene_families_tsv(output: str, compress: bool = False):
    """
    Write the file providing the association between genes and gene families

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info("Writing the file providing the association between genes and gene families...")
    outname = output + "/gene_families.tsv"
    with write_compressed_or_not(outname, compress) as tsv:
        for fam in pan.gene_families:
            for gene in fam.genes:
                tsv.write("\t".join([fam.name, gene.ID if gene.local_identifier == "" else gene.local_identifier,
                                     "F" if gene.is_fragment else ""]) + "\n")
    logging.getLogger().info("Done writing the file providing the association between genes and "
                             f"gene families : '{outname}'")


def write_regions(output, compress=False):
    """
    Write the file providing information about RGP content

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    fname = output + "/plastic_regions.tsv"
    with write_compressed_or_not(fname, compress) as tab:
        tab.write("region\torganism\tcontig\tstart\tstop\tgenes\tcontigBorder\twholeContig\n")
        regions = sorted(pan.regions, key=lambda x: (x.organism.name, x.contig.name, x.start))
        for region in regions:
            tab.write('\t'.join(map(str, [region.name, region.organism, region.contig, region.start, region.stop,
                                          len(region.genes), region.is_contig_border, region.is_whole_contig])) + "\n")


def summarize_spots(spots: set, output: str, compress: bool = False):
    """
    Write a file providing summarize information about hotspots

    :param spots: set of spots in pangenome
    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    def r_and_s(value: float):
        """rounds to dp figures and returns a str of the provided value"""
        return str(round(value, 3)) if isinstance(value, float) else str(value)

    with write_compressed_or_not(output + "/summarize_spots.tsv", compress) as fout:
        fout.write("spot\tnb_rgp\tnb_families\tnb_unique_family_sets\tmean_nb_genes\t"
                   "stdev_nb_genes\tmax_nb_genes\tmin_nb_genes\n")
        for spot in sorted(spots, key=lambda x: len(x.regions), reverse=True):
            tot_fams = set()
            rgp_list = list(spot.regions)
            len_uniq_content = len(spot.get_uniq_content())
            size_list = []
            for rgp in spot.regions:
                tot_fams |= rgp.families
                size_list.append(len(rgp.genes))
            mean_size = mean(size_list)
            stdev_size = stdev(size_list) if len(size_list) > 1 else 0
            max_size = max(size_list)
            min_size = min(size_list)
            fout.write("\t".join(map(r_and_s, [f"spot_{spot.ID}", len(rgp_list), len(tot_fams), len_uniq_content,
                                               mean_size, stdev_size, max_size, min_size])) + "\n")
    logging.getLogger().info(f"Done writing spots in : '{output + '/summarize_spots.tsv'}'")


def spot2rgp(spots: set, output: str, compress: bool = False):
    """Write a tsv file providing association between spot and rgp

    :param spots: set of spots in pangenome
    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    with write_compressed_or_not(output + "/spots.tsv", compress) as fout:
        fout.write("spot_id\trgp_id\n")
        for spot in spots:
            for rgp in spot.regions:
                fout.write(f"spot_{spot.ID}\t{rgp.name}\n")


def write_spots(output, compress):
    """ Write tsv files providing spots information and association with RGP

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    if len(pan.spots) > 0:
        spot2rgp(pan.spots, output, compress)
        summarize_spots(pan.spots, output, compress)


def write_borders(output: str, dup_margin: float = 0.05, compress: bool = False):
    """Write all gene families bordering each spot

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    :param dup_margin: minimum ratio of organisms in which family must have multiple genes to be considered duplicated
    """
    multigenics = pan.get_multigenics(dup_margin=dup_margin)
    all_fams = set()
    with write_compressed_or_not(output + "/spot_borders.tsv", compress) as fout:
        fout.write("spot_id\tnumber\tborder1\tborder2\n")
        for spot in sorted(pan.spots, key=lambda x: len(x.regions), reverse=True):
            curr_borders = spot.borders(pan.parameters["spots"]["set_size"], multigenics)
            for c, border in curr_borders:
                famstring1 = ",".join([fam.name for fam in border[0]])
                famstring2 = ",".join([fam.name for fam in border[1]])
                all_fams |= set(border[0])
                all_fams |= set(border[1])
                fout.write(f"{spot.ID}\t{c}\t{famstring1}\t{famstring2}\n")

    with write_compressed_or_not(output + "/border_protein_genes.fasta", compress) as fout:
        for fam in all_fams:
            fout.write(f">{fam.name}\n")
            fout.write(f"{fam.sequence}\n")


def write_module_summary(output: str, compress: bool = False):
    """
    Write a file providing summarize information about modules

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info("Writing functional modules summary...")
    with write_compressed_or_not(output + "/modules_summary.tsv", compress) as fout:
        fout.write("module_id\tnb_families\tnb_organisms\tpartition\tmean_number_of_occurrence\n")
        for mod in pan.modules:
            org_dict = defaultdict(set)
            partition_counter = Counter()
            for family in mod.families:
                partition_counter[family.named_partition] += 1
                for gene in family.genes:
                    org_dict[gene.organism].add(gene)
            fout.write(
                f"module_{mod.ID}\t{len(mod.families)}\t{len(org_dict)}\t{partition_counter.most_common(1)[0][0]}\t"
                f"{round((sum([len(genes) for genes in org_dict.values()]) / len(org_dict)) / len(mod.families), 3)}\n")
        fout.close()

    logging.getLogger().info(f"Done writing module summary: '{output + '/modules_summary.tsv'}'")


def write_modules(output: str, compress: bool = False):
    """Write a tsv file providing association between modules and gene families

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info("Writing functional modules...")
    with write_compressed_or_not(output + "/functional_modules.tsv", compress) as fout:
        fout.write("module_id\tfamily_id\n")
        for mod in pan.modules:
            for family in mod.families:
                fout.write(f"module_{mod.ID}\t{family.name}\n")
        fout.close()

    logging.getLogger().info(f"Done writing functional modules to: '{output + '/functional_modules.tsv'}'")


def write_org_modules(output, compress):
    """Write a tsv file providing association between modules and organisms

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info("Writing modules to organisms associations...")
    with write_compressed_or_not(output + "/modules_in_organisms.tsv", compress) as fout:
        fout.write("module_id\torganism\tcompletion\n")
        for mod in pan.modules:
            mod_orgs = set()
            for fam in mod.families:
                mod_orgs |= fam.organisms
            for org in mod_orgs:
                completion = round(len(org.families & mod.families) / len(mod.families), 2)
                fout.write(f"module_{mod.ID}\t{org.name}\t{completion}\n")
        fout.close()
    logging.getLogger().info(
        f"Done writing modules to organisms associations to: '{output + '/modules_in_organisms.tsv'}'")


def write_spot_modules(output, compress):
    """Write a tsv file providing association between modules and spots

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info("Writing modules to spot associations...")

    fam2mod = {}
    for mod in pan.modules:
        for fam in mod.families:
            fam2mod[fam] = mod

    with write_compressed_or_not(output + "/modules_spots.tsv", compress) as fout:
        fout.write("module_id\tspot_id\n")

        for spot in pan.spots:
            curr_mods = defaultdict(set)
            for rgp in spot.get_uniq_content():
                for fam in rgp.families:
                    mod = fam2mod.get(fam)
                    if mod is not None:
                        curr_mods[mod].add(fam)

            for mod in curr_mods:
                if curr_mods[mod] == mod.families:
                    # if all the families in the module are found in the spot, write the association
                    fout.write(f"module_{mod.ID}\tspot_{spot.ID}\n")

    logging.getLogger().info(f"Done writing module to spot associations to: {output + '/modules_spots.tsv'}")


def write_rgp_modules(output, compress):
    """Write a tsv file providing association between modules and RGP

    :param output: Path to output directory
    :param compress: Compress the file in .gz
    """
    logging.getLogger().info("Clustering RGPs based on module content...")

    lists = write_compressed_or_not(output + "/modules_RGP_lists.tsv", compress)
    lists.write("representative_RGP\tnb_spots\tmod_list\tRGP_list\n")
    fam2mod = {}
    for mod in pan.modules:
        for fam in mod.families:
            fam2mod[fam] = mod

    region2spot = {}
    for spot in pan.spots:
        for region in spot.regions:
            region2spot[region] = spot

    mod_group2rgps = defaultdict(list)

    for region in pan.regions:
        curr_mod_list = set()
        for fam in region.families:
            mod = fam2mod.get(fam)
            if mod is not None:
                curr_mod_list.add(mod)
        if curr_mod_list != set():
            mod_group2rgps[frozenset(curr_mod_list)].append(region)

    for mod_list, regions in mod_group2rgps.items():
        spot_list = set()
        for region in regions:
            myspot = region2spot.get(region)
            if myspot is not None:
                spot_list.add(region2spot[region])
        lists.write(f"{regions[0].name}\t{len(spot_list)}\t{','.join(['module_' + str(mod.ID) for mod in mod_list])}\t"
                    f"{','.join([reg.name for reg in regions])}\n")
    lists.close()

    logging.getLogger().info(f"RGP and associated modules are listed in : {output + '/modules_RGP_lists.tsv'}")


def write_flat_files(pangenome: Pangenome, output: str, cpu: int = 1, soft_core: float = 0.95, dup_margin: float = 0.05,
                     csv: bool = False, gene_pa: bool = False, gexf: bool = False, light_gexf: bool = False,
                     projection: bool = False, stats: bool = False, json: bool = False, partitions: bool = False,
                     regions: bool = False, families_tsv: bool = False, spots: bool = False, borders: bool = False,
                     modules: bool = False, spot_modules: bool = False, compress: bool = False,
                     disable_bar: bool = False):
    """
    Main function to write flat files from pangenome

    :param pangenome: Pangenome object
    :param output: Path to output directory
    :param cpu: Number of available core
    :param soft_core: Soft core threshold to use
    :param dup_margin: minimum ratio of organisms in which family must have multiple genes to be considered duplicated
    :param csv: write csv file format as used by Roary
    :param gene_pa: write gene presence abscence matrix
    :param gexf: write pangenome graph in gexf format
    :param light_gexf: write pangenome graph with only gene families
    :param projection: write projection of pangenome for organisms
    :param stats: write statistics about pangenome
    :param json: write pangenome graph in json file
    :param partitions: write the gene families for each partition
    :param regions: write information on RGP
    :param families_tsv: write gene families information
    :param spots: write information on spots
    :param borders: write gene families bordering spots
    :param modules: write information about modules
    :param spot_modules: write association between modules and RGP and modules and spots
    :param compress: Compress the file in .gz
    :param disable_bar: Disable progress bar
    """
    # TODO Add force parameter to check if output already exist
    if not any(x for x in [csv, gene_pa, gexf, light_gexf, projection, stats, json, partitions, regions, spots, borders,
                           families_tsv, modules, spot_modules]):
        raise Exception("You did not indicate what file you wanted to write.")

    processes = []
    global pan
    global needAnnotations
    global needFamilies
    global needGraph
    global needPartitions
    global needSpots
    global needRegions
    global needModules
    global ignore_err

    pan = pangenome

    if csv or gene_pa or gexf or light_gexf or projection or stats or json or partitions or regions or spots or \
            families_tsv or borders or modules or spot_modules:
        needAnnotations = True
        needFamilies = True
    if projection or stats or partitions or regions or spots or borders:
        needPartitions = True
    if gexf or light_gexf or json:
        needGraph = True
    if regions or spots or borders or spot_modules:
        needRegions = True
    if spots or borders or spot_modules:  # or projection:
        needSpots = True
    if modules or spot_modules:  # or projection:
        needModules = True
    if projection:
        needRegions = True if pan.status["predictedRGP"] == "inFile" else False
        needSpots = True if pan.status["spots"] == "inFile" else False
        needModules = True if pan.status["modules"] == "inFile" else False

    check_pangenome_info(pan, need_annotations=needAnnotations, need_families=needFamilies, need_graph=needGraph,
                         need_partitions=needPartitions, need_rgp=needRegions, need_spots=needSpots,
                         need_modules=needModules, disable_bar=disable_bar)

    pan.get_org_index()  # make the index because it will be used most likely
    with get_context('fork').Pool(processes=cpu) as p:
        if csv:
            processes.append(p.apply_async(func=write_matrix, args=(output, ',', "csv", compress, True)))
        if gene_pa:
            processes.append(p.apply_async(func=write_gene_presence_absence, args=(output, compress)))
        if gexf:
            processes.append(p.apply_async(func=write_gexf, args=(output, False, soft_core)))
        if light_gexf:
            processes.append(p.apply_async(func=write_gexf, args=(output, True, soft_core)))
        if projection:
            processes.append(p.apply_async(func=write_projections, args=(output, compress)))
        if stats:
            processes.append(p.apply_async(func=write_stats, args=(output, soft_core, dup_margin, compress)))
        if json:
            processes.append(p.apply_async(func=write_json, args=(output, compress)))
        if partitions:
            processes.append(p.apply_async(func=write_parts, args=(output, soft_core)))
        if families_tsv:
            processes.append(p.apply_async(func=write_gene_families_tsv, args=(output, compress)))
        if regions:
            processes.append(p.apply_async(func=write_regions, args=(output, compress)))
        if spots:
            processes.append(p.apply_async(func=write_spots, args=(output, compress)))
        if borders:
            processes.append(p.apply_async(func=write_borders, args=(output, dup_margin, compress)))
        if modules:
            processes.append(p.apply_async(func=write_modules, args=(output, compress)))
            processes.append(p.apply_async(func=write_module_summary, args=(output, compress)))
            processes.append(p.apply_async(func=write_org_modules, args=(output, compress)))
        if spot_modules:
            processes.append(p.apply_async(func=write_spot_modules, args=(output, compress)))
            processes.append(p.apply_async(func=write_rgp_modules, args=(output, compress)))

        for process in processes:
            process.get()  # get all the results


def launch(args: argparse.Namespace):
    """
    Command launcher

    :param args: All arguments provide by user
    """
    mk_outdir(args.output, args.force)
    global pan
    pan.add_file(args.pangenome)
    write_flat_files(pan, args.output, cpu=args.cpu, soft_core=args.soft_core, dup_margin=args.dup_margin, csv=args.csv,
                     gene_pa=args.Rtab, gexf=args.gexf, light_gexf=args.light_gexf, projection=args.projection,
                     stats=args.stats, json=args.json, partitions=args.partitions, regions=args.regions,
                     families_tsv=args.families_tsv, spots=args.spots, borders=args.borders, modules=args.modules,
                     spot_modules=args.spot_modules, compress=args.compress, disable_bar=args.disable_prog_bar)


def subparser(sub_parser: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """
    Subparser to launch PPanGGOLiN in Command line

    :param sub_parser : sub_parser for align command

    :return : parser arguments for align command
    """
    parser = sub_parser.add_parser("write", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser_flat(parser)
    return parser


def parser_flat(parser: argparse.ArgumentParser):
    """
    Parser for specific argument of write command

    :param parser: parser for align argument
    """
    required = parser.add_argument_group(title="Required arguments",
                                         description="One of the following arguments is required :")
    required.add_argument('-p', '--pangenome', required=True, type=str, help="The pangenome .h5 file")
    required.add_argument('-o', '--output', required=True, type=str,
                          help="Output directory where the file(s) will be written")
    optional = parser.add_argument_group(title="Optional arguments")
    optional.add_argument("--soft_core", required=False, type=restricted_float, default=0.95,
                          help="Soft core threshold to use")
    optional.add_argument("--dup_margin", required=False, type=restricted_float, default=0.05,
                          help="minimum ratio of organisms in which the family must have multiple genes "
                               "for it to be considered 'duplicated'")
    optional.add_argument("--gexf", required=False, action="store_true",
                          help="write a gexf file with all the annotations and all the genes of each gene family")
    optional.add_argument("--light_gexf", required=False, action="store_true",
                          help="write a gexf file with the gene families and basic informations about them")
    optional.add_argument("--csv", required=False, action="store_true",
                          help="csv file format as used by Roary, among others. "
                               "The alternative gene ID will be the partition, if there is one")
    optional.add_argument("--Rtab", required=False, action="store_true",
                          help="tabular file for the gene binary presence absence matrix")
    optional.add_argument("--projection", required=False, action="store_true",
                          help="a csv file for each organism providing information on the projection of the graph "
                               "on the organism")
    optional.add_argument("--stats", required=False, action="store_true",
                          help="tsv files with some statistics for each organism and for each gene family")
    optional.add_argument("--partitions", required=False, action="store_true",
                          help="list of families belonging to each partition, with one file per partitions and "
                               "one family per line")
    optional.add_argument("--compress", required=False, action="store_true", help="Compress the files in .gz")
    optional.add_argument("--json", required=False, action="store_true", help="Writes the graph in a json file format")
    optional.add_argument("--regions", required=False, action="store_true",
                          help="Write the RGP in a tab format, one file per genome")
    optional.add_argument("--spots", required=False, action="store_true",
                          help="Write spot summary and a list of all RGP in each spot")
    optional.add_argument("--borders", required=False, action="store_true", help="List all borders of each spot")
    optional.add_argument("--modules", required=False, action="store_true",
                          help="Write a tsv file listing functional modules and the families that belong to them")
    optional.add_argument("--families_tsv", required=False, action="store_true",
                          help="Write a tsv file providing the association between genes and gene families")
    optional.add_argument("--spot_modules", required=False, action="store_true",
                          help="writes 3 files comparing the presence of modules within spots")


if __name__ == '__main__':
    """To test local change and allow using debugger"""
    from ppanggolin.utils import check_log, set_verbosity_level

    main_parser = argparse.ArgumentParser(
        description="Depicting microbial species diversity via a Partitioned PanGenome Graph Of Linked Neighbors",
        formatter_class=argparse.RawTextHelpFormatter)

    parser_flat(main_parser)
    common = main_parser.add_argument_group(title="Common argument")
    common.add_argument("--verbose", required=False, type=int, default=1, choices=[0, 1, 2],
                        help="Indicate verbose level (0 for warning and errors only, 1 for info, 2 for debug)")
    common.add_argument("--log", required=False, type=check_log, default="stdout", help="log output file")
    common.add_argument("-d", "--disable_prog_bar", required=False, action="store_true",
                        help="disables the progress bars")
    common.add_argument("-c", "--cpu", required=False, default=1, type=int, help="Number of available cpus")
    common.add_argument('-f', '--force', action="store_true",
                        help="Force writing in output directory and in pangenome output file.")
    set_verbosity_level(main_parser.parse_args())
    launch(main_parser.parse_args())
