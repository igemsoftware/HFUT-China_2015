"""
gene.py realize the methods that are related to system recommendation.

@author: Bowen
"""

from system.models import gene, reaction, compound, reaction_compound, compound_gene
from system.fasta_reader import parse_fasta_str
from elasticsearch import Elasticsearch
import traceback
import urllib2
import json

def search_compound(keyword):
    """
    search compound based on the keyword

    @param keyword: the keyword that the user typed. Which would be used in search
    @type keyword: str
    @return: return a list that contains searched compounds
    @rtype: list
    """

    es = Elasticsearch()
    result = format_fuzzy_result(fuzzy_search_compound(es, keyword))
    return result

def fuzzy_search_compound(es, keyword):
    """
    fuzzy search compound based on the keyword with elasticsearch

    @param es: the elasticsearch object
    @param keyword: the search keyword
    @type es: Elasticsearch
    @type keyword: str
    @return a dict generated by the elasticsearch, which contains the search result
    @rtype: dict
    """

    query_body = {
        "from" : 0,
        "size" : 20,
        "query" : {
            "fuzzy_like_this" : {
                "fields" : ["name"],
                "like_text" : keyword,
                "max_query_terms" : 20
            }
        }
    }
    result = es.search(index="biodesigners", doc_type="compounds", body=query_body)
    return result

def format_fuzzy_result(es_result):
    """
    format the es search result to front end processable format

    @param es_result: the es search result
    @type es_result: dict
    @return: the front end processable format, while will be like this::
        [{'compound_id': id, 'name': name},...]
    @rtype: list
    """

    compound_result = es_result['hits']['hits']
    result = list()
    if len(compound_result) != 0:
        for compound_item in compound_result:
            info = compound_item['_source']
            compound_info = {
                'compound_id': info["compound_id"],
                'name': info['name'],
            }
            result.append(compound_info)
    return result

def get_gene_info(gid):
    try:
        gene_obj = gene.objects.get(gene_id=gid)
        result = {
            'gene_id': gene_obj.gene_id,
            'name': gene_obj.name,
            'definition': gene_obj.definition,
            'organism_short': gene_obj.organism_short,
            'organism': gene_obj.organism
        }
        return True, result
    except:
        traceback.print_exc()
        return False, None

def get_compound_info(cid):
    """
    get a specific compound's information

    @param cid: compound id
    @type cid: str
    @return: a tunple that contains is compound can be retrived and the information
    @rtype: dict
    """

    try:
        compound_obj = compound.objects.get(compound_id=cid)
        result = {
            'compound_id' : compound_obj.compound_id,
            'name': compound_obj.name,
            'nicknames' : compound_obj.nicknames.replace('_', '\n'),
            'formula' : compound_obj.formula,
            'exact_mass' : compound_obj.exact_mass,
            'mol_weight' : compound_obj.mol_mass
        }
        return True, result
    except:
        traceback.print_exc()
        return False, None

def retrive_gene_detain(gid):
    #get information from ncbi
    baseUrl = 'http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=gene&retmode=json&version=2.0&id='
    req = urllib2.Request(baseUrl + gid)
    response = urllib2.urlopen(req)
    resStr = response.read()
    result = json.loads(resStr)
    infos = result['result'][gid]
    detail_info = dict()
    detail_info['name'] = infos['name']
    detail_info['definition'] = infos['description']
    detail_info['organism'] = infos['organism']['scientificname']
    return detail_info

def get_or_create_gene(gid):
    #get in database
    try:
        gene_obj = gene.objects.get(gene_id=gid)
        return gene_obj
    except:
        #get from ncbi
        baseUrl = 'http://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&rettype=fasta&id='
        req = urllib2.Request(baseUrl + gid)
        response = urllib2.urlopen(req)
        resStr = response.read()
        gene_dict = parse_fasta_str(resStr)
        for gn in gene_dict.keys():
            gid = gn.split('|')[1]
            #get detail information
            new_gene_obj = gene(gene_id=gid)
            detail_info = retrive_gene_detain(gid)
            new_gene_obj.name = detail_info['name']
            new_gene_obj.definition = detail_info['definition']
            new_gene_obj.organism = detail_info['organism']
            new_gene_obj.ntseq = gene_dict[gn]
            new_gene_obj.ntseq_length = len(gene_dict[gn])
            try:
                new_gene_obj.save()
                return new_gene_obj
            except:
                pass
        return None


def save_relation_to_db(geneIdList, compound_obj):
    #create new obj
    for gid in geneIdList:
        new_rela_obj = compound_gene(compound=compound_obj)
        gene_obj = get_or_create_gene(gid)
        new_rela_obj.gene = gene_obj
        try:
            new_rela_obj.save()
        except:
            pass

def search_gene_in_ncbi(name, expect=None, index=0):
    #find in database
    compound_obj = None
    try:
        compound_obj = compound.objects.get(name=name)
    except:
        compound_obj = get_compound(name)
    if compound_obj == None:
        return None
    obj_list = compound_gene.objects.filter(compound=compound_obj)
    if len(obj_list) != 0:
        geneIdList = list()
        for obj in obj_list:
            geneIdList.append(obj.gene.gene_id)
        return geneIdList
    #retrive from kegg
    baseGeneFindUrl = 'http://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=gene&retmode=json&term='
    try:
        req = urllib2.Request(baseGeneFindUrl + name)
        response = urllib2.urlopen(req)
        resStr = response.read()
    except:
        traceback.print_exc()
        return None
    if len(resStr) == 0:
        return None
    result = json.loads(resStr)
    geneIdList = result['esearchresult']['idlist']
    save_relation_to_db(geneIdList, compound_obj)
    if expect != None:
        del geneIdList[geneIdList.index(expect)]
    return geneIdList[:5]

def find_related_compound(cid_str):
    """
    find the compound that are related to current compound in reaction

    @param cid: list of compound id
    @type cid: list 
    @return: dict of compound that are related to the compound, empty list will be returned if there is no related compound
    @rtype: dict
    """
    result = dict()
    nodes = list()
    edges = list()
    all_genes = list()
    index_dict = dict()
    index = 0
    if cid_str.endswith('_'):
        cid_str = cid_str[:-1]
    cid_list = cid_str.split('_')
    for cid in cid_list:
        try:
            compound_obj = compound.objects.get(compound_id=cid)
            #get first gene and create new node
            cen_gene_id = None
            try:
                cen_gene_id = search_gene_in_ncbi(compound_obj.name,)[0]
                if not cen_gene_id in all_genes:
                    all_genes.append(cen_gene_id)
                    gene_obj = gene.objects.get(gene_id=cen_gene_id)
                    node_info = {
                        'name': gene_obj.name,
                        'id': gene_obj.gene_id
                    }
                    nodes.append(node_info)
                    index_dict[cen_gene_id] = index
                    index += 1
            except:
                pass
            # find related reactions
            related_rctns = reaction_compound.objects.filter(compound=compound_obj, isReactant=True)
            for rc_obj in related_rctns:
                cid = rc_obj.compound.compound_id
                cname = rc_obj.compound.name
                # find genes
                gene_list = search_gene_in_ncbi(cname, expect=cen_gene_id, index=1)
                print gene_list
                for gene_id in gene_list:
                    if gene_id in all_genes:
                        continue
                    try:
                        gene_obj = gene.objects.get(gene_id=gene_id)
                        #create new node
                        all_genes.append(gene_id)
                        node_info = {
                            'name' : gene_obj.name,
                            'id': gene_obj.gene_id
                        }
                        nodes.append(node_info)
                        index_dict[gene_obj.gene_id] = index
                        index += 1
                        # add edge
                        edge_info = {
                            'source': index_dict[cen_gene_id],
                            'target': index_dict[gene_obj.gene_id],
                            'relation': cname
                        }
                        edges.append(edge_info)
                    except:
                        traceback.print_exc()
                        pass
        except:
            traceback.print_exc()
            pass
        result = {
            'nodes': nodes,
            'edges': edges
        }
        return result