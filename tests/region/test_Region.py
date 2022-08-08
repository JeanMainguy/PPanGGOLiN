#! /usr/bin/env python3

import pytest

from ppanggolin.region import Region
from ppanggolin.geneFamily import GeneFamily
from ppanggolin.genome import Gene, Contig, Organism, RNA


# ================================================
def test_cstr():
    identifier = 4
    o_region = Region(identifier)
    assert isinstance(o_region, Region)
    for attr in "genes", "name", "score":
        assert hasattr(o_region, attr)

    assert o_region.score == 0
    assert o_region.name == identifier
    assert o_region.genes == []


# ================================================
@pytest.fixture
def o_region():
    return Region(4)


@pytest.fixture
def o_org():
    return Organism("toto")


@pytest.fixture
def o_contig():
    return Contig(1)


@pytest.fixture
def o_rna(o_contig):
    o_rna = RNA("Ah")
    o_rna.fill_annotations(35, 45, "-")
    o_contig.add_rna(o_rna)
    return o_rna


@pytest.fixture
def l_genes(o_org, o_contig):
    """ creates a small gene set for testing.

        returns a list of 4 genes that belongs
        to the same contig and the same organism."""
    l_genes = []
    c = 10
    for i, gene_id in enumerate([
        "toto", "tata", "titi", "tutu",
        "lolo", "lala", "lili", "lulu",
    ]):
        gene = Gene(gene_id)
        gene.fill_annotations(c, c + 30, "+", position=i)
        gene.fill_parents(o_org, o_contig)
        o_contig.add_gene(gene)
        gene.family = GeneFamily(i, gene_id)
        gene.family.add_partition("c-cloud")
        l_genes.append(gene)
        c += 35
    return l_genes


# ================================================
def test_append(l_genes, o_region):
    for gene in l_genes:
        o_region.append(gene)

    assert set(o_region.genes) == set(l_genes)


def test_append__error(o_region):
    """append should raise a TypeError is used with non Gene param."""
    with pytest.raises(TypeError):
        o_region.append(42)


def test_properties(l_genes, o_region, o_org, o_contig):
    """All properties expect a region with genes."""
    s_families = set()
    for gene in l_genes:
        o_region.append(gene)
        s_families.add(gene.family)

    # checking properties sanity
    assert o_region.start == o_region.start_gene.start
    assert o_region.stop == o_region.stop_gene.stop
    assert o_region.organism == o_org
    assert o_region.families == s_families
    assert o_region.contig == o_contig
    assert o_region.is_whole_contig is True
    assert o_region.is_contig_border is True  # first contig gene is in the region

    # remove the first gene of the contig
    o_region.genes.pop(0)
    assert o_region.is_contig_border is True  # last contig gene is in the region

    # remove the last gene of the contig
    # => the whole contig is not in the Region anymore
    o_region.genes.pop()
    assert o_region.is_whole_contig is False
    assert o_region.is_contig_border is False


def test_is_contig_border(o_region):
    """is_contig_border raise an exception
       when the region contain no genes.
    """
    with pytest.raises(Exception):
        o_region.is_contig_border


def test_get_rnas(o_rna, o_region, l_genes):
    for gene in l_genes:
        o_region.append(gene)
    assert set(o_region.get_rnas()) == {o_rna}


def test_hash(o_region):
    """ a hash function returns an integer"""
    # the same int if called twice on the same object
    h = hash(o_region)
    assert isinstance(h, int)
    assert h == hash(o_region)

    # different ints if called on objects representing the same entity
    name = "charming"
    assert hash(Region(name)) != hash(Region(name))


def test_equality(o_region, l_genes):
    """2 regions are equals if they contain the same list of genes."""
    for gene in l_genes:
        o_region.append(gene)

    # not the same list => False
    o_other = Region("other")
    assert o_region != o_other

    # the exact same list => True
    o_other = Region("other")
    for gene in l_genes:
        o_other.append(gene)
    assert o_region == o_other

    # the same list in reverse order => True
    o_other = Region("other")
    for gene in reversed(l_genes):
        o_other.append(gene)
    assert o_region == o_other


def test_equality__error(o_region):
    """equality raises error if not compared to another Region"""
    with pytest.raises(TypeError):
        o_region == 42


def test_len(o_region, l_genes):
    assert 0 == len(o_region)

    for gene in l_genes:
        o_region.append(gene)
    assert len(l_genes) == len(o_region)


def test_get_item(o_region, l_genes):
    with pytest.raises(IndexError):
        o_region[1]

    for gene in l_genes:
        o_region.append(gene)
    assert o_region[2] == l_genes[2]


def test_get_bordering_genes(o_region, l_genes):
    # return at most n-1 genes not in multigenics families
    # nor in family with persistent partition.

    print("\n")
    for gene in l_genes:
        o_region.append(gene)

    l_first, l_last = o_region.get_bordering_genes(0, ['f1', 'f2'])
    assert [] == l_first
    assert [] == l_last

    # line 101 & 125 != while condition. => unreachable lines.
    # return nothing if is_contig_border
    l_first, l_last = o_region.get_bordering_genes(2, ['f1', 'f2'])
    assert [] == l_first
    assert [] == l_last

    # remove first and last gene
    o_region.genes.pop(0)
    o_region.genes.pop()
    o_region.get_bordering_genes(4, ['f1', 'f2'])
