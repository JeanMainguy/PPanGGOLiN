#! /usr/bin/env python3

import pytest
from random import randint, sample

from collections import defaultdict

from ppanggolin.pangenome import Edge
from ppanggolin.geneFamily import GeneFamily
from ppanggolin.genome import Gene


def test_cstr():
    identifier = 33
    name = "33"
    o_family = GeneFamily(identifier, name)
    assert isinstance(o_family, GeneFamily)

    for attr in "ID", "name", "genes", \
                "removed", "sequence", "partition":
        assert hasattr(o_family, attr)
    assert o_family.ID == identifier
    assert o_family.name == name
    assert o_family.genes == set()
    assert o_family.removed is False
    assert o_family.sequence == ""
    assert o_family.partition == ""


@pytest.fixture()
def o_family():
    return GeneFamily(33, "trente-trois")


def test_add_sequence(o_family):
    seq = "un de troa"
    o_family.add_sequence(seq)
    assert o_family.sequence == seq


def test_add_partition(o_family):
    partition = "un de troa"
    o_family.add_partition(partition)
    assert o_family.partition == partition


def test_named_partition_error(o_family):
    with pytest.raises(Exception):
        o_family.named_partition


@pytest.mark.parametrize("partition, name",
                         [
                             ("P", "persistent"),
                             ("Pp", "persistent"),
                             ("P whatever, only first letter is important", "persistent"),
                             ("C", "cloud"),
                             ("C loud", "cloud"),
                             ("C whatever, only first letter is important", "cloud"),
                             ("S", "shell"),
                             ("Shut", "shell"),
                             ("S whatever, only first letter is important", "shell"),
                             ("un de troa kvar", "undefined"),
                             ("1", "undefined"),
                             ("p", "undefined"),
                             ("c", "undefined"),
                             ("s", "undefined"),
                         ])
def test_named_partition(o_family, partition, name):
    o_family.add_partition(partition)
    assert o_family.named_partition == name


@pytest.fixture()
def lo_genes():
    return [Gene(str(i)) for i in range(4)]


def test_add_gene_error(o_family, lo_genes):
    with pytest.raises(TypeError):
        o_family.add_gene(33)


def test_add_gene_solo(o_family, lo_genes):
    o_gene = Gene(33)
    o_family.add_gene(o_gene)
    assert o_family.genes == {o_gene}
    assert o_gene.family == o_family


def test_add_gene_many(o_family, lo_genes):
    """ fill the family with genes from the same organism"""
    organism = "organism"
    for o_gene in lo_genes * 4:  # *4 to assert duplicates are not considered
        o_gene.fill_parents(organism, None)
        o_family.add_gene(o_gene)
        assert o_gene.family == o_family
    assert o_family.genes == set(lo_genes)


def test_mk_bitarray_no_org(o_family):
    # index is meaningless
    o_family.mk_bitarray(None)
    assert o_family.bitarray == 0


def test_mk_bitarray_with_org(o_family):
    organism = "organism"
    o_gene = Gene(33)
    o_gene.fill_parents(organism, None)

    o_family.add_gene(o_gene)

    for i in 1, 3, 7, 12:
        index = {organism: i}
        o_family.mk_bitarray(index)
        assert o_family.bitarray == 1 << i


def test_get_org_dict_error(o_family):
    with pytest.raises(AttributeError):
        o_family.discard('_genePerOrg')
        # I don't get how this can happen


def test_get_org_dict_empty(o_family):
    dd = o_family.get_org_dict()
    assert isinstance(dd, defaultdict)
    assert 0 == len(dd)


def test_get_org_dict(o_family, lo_genes):
    """ in lo_genes, none has organism.
        I'll add one, several times, creating several sets."""
    n_orgs = randint(2, 10)
    for org in range(n_orgs):
        for o_gene in lo_genes:
            o_gene.fill_parents(org, None)
            o_family.add_gene(o_gene)

    dd = o_family.get_org_dict()
    assert n_orgs == len(dd)
    for org in dd:
        assert dd[org] == set(lo_genes)

    # Note: after integration, genes can be edited
    #   which leads to inconsistent results.
    #   here the same genes are refered to 2 orgs.
    #   IMO this would be user pb as it is insane user behavior.


def test_get_genes_per_org_error(o_family):
    with pytest.raises(AttributeError):
        o_family.discard('_genePerOrg')
        # I don't get how this can happen


def test_get_genes_per_org_no_gene(o_family):
    org = "org"

    s_genes = o_family.get_genes_per_org(org)
    assert 0 == len(s_genes)


def test_get_genes_per_org(o_family, lo_genes):
    org = "org"
    for o_gene in lo_genes:
        o_gene.fill_parents(org, None)
        o_family.add_gene(o_gene)
    s_genes = o_family.get_genes_per_org(org)
    assert s_genes == set(lo_genes)


def test_organisms_error(o_family, lo_genes):
    with pytest.raises(AttributeError):
        o_family.discard('_genePerOrg')
        # I don't get how this can happen


def test_organisms_empty(o_family, lo_genes):
    assert set() == o_family.organisms


def test_organisms(o_family, lo_genes):
    l_org = []
    for o_gene in lo_genes:
        org = randint(0, 5)
        o_gene.fill_parents(org, None)
        o_family.add_gene(o_gene)
        l_org.append(org)

    assert set(l_org) == o_family.organisms


def test_neighbors_empty(o_family):
    assert o_family.neighbors == set()


@pytest.fixture
def filled_families():
    """
    return a list of families and genes.
    there will be between 3 and 10 genes/families.
    Each family has only one gene.
    """
    lo_genes = []
    lo_fam = []

    n_families = randint(3, 10)
    for fam in range(n_families):
        o_gene = Gene(fam)
        o_gene.fill_parents(None, None)

        o_family = GeneFamily(fam, fam)
        o_family.add_gene(o_gene)

        lo_genes.append(o_gene)
        lo_fam.append(o_family)

    return lo_fam, lo_genes


def test_neighbors(filled_families):
    lo_fam, lo_genes = filled_families

    # get several genes and make an edge
    #   between them and the first of the list
    n_genes = randint(2, len(lo_genes))
    sample_genes = sample(lo_genes, n_genes)
    for o_gene in sample_genes:
        # it is strange to me to update family attribute from another class.
        Edge(lo_genes[0], o_gene)
    # we have 0->{*}

    # first gene belong to the first family
    # let's get the family neighbors
    # set because order is not guaranted
    s = set(lo_fam[0].neighbors)
    print(s)
    assert n_genes == len(s)

    xpected = {g.family for g in sample_genes}
    assert xpected == s


def test_edges_empty(o_family):
    d = o_family.edges
    assert 0 == len(d)


def test_edges(filled_families):
    lo_fam, lo_genes = filled_families

    # get several genes and make an edge
    #   between them and the first of the list
    n_genes = randint(2, len(lo_genes))
    sample_genes = sample(lo_genes, n_genes)
    l_edges = []
    for o_gene in sample_genes:
        # it is strange to me to update family attribute from another class.
        l_edges.append(Edge(lo_genes[0], o_gene))
    # we have 0->{*}

    edge_list = lo_fam[0].edges
    # set because order is not guaranted
    assert set(l_edges) == set(edge_list)
