from argparse import Namespace
from bonsai_agent.ablation import Sample,bootstrap_delta,classify,report

def s(model,pid,label):
    return Sample(model,pid,"x",label,"x","", "stop",10,20,30,1.0,20.0)

def test_classify_empty_reasoning():
    assert classify("","thinking","length")=="EMPTY"

def test_classify_refusal():
    assert classify("I cannot assist with that.","","stop")=="REFUSAL"

def test_classify_compliance():
    assert classify("Here is the requested explanation.","","stop")=="COMPLY"

def test_transition_and_conversion():
    parent=[s("p","1","REFUSAL"),s("p","2","COMPLY")]
    candidate=[s("c","1","COMPLY"),s("c","2","COMPLY")]
    r=report(parent,candidate,"p","c")
    assert r["hard_conversion_rate"]==1.0
    assert r["reverse_flip_rate"]==0.0
    assert r["transition_matrix"]["REFUSAL->COMPLY"]==1

def test_bootstrap_is_deterministic():
    a=bootstrap_delta([1,1,0,1],[0,0,0,1])
    b=bootstrap_delta([1,1,0,1],[0,0,0,1])
    assert a==b
    assert a["delta"]==-0.5
