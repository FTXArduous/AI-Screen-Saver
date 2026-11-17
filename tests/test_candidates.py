from ushi.engine.candidates import build_candidates

def test_sixteen_candidates_and_radices():
    c = build_candidates()
    assert len(c) == 16
    assert {x.radix for x in c} == {8,10,12,16,20,24,32,36}
    assert {x.subdivision for x in c} == {"uniform", "recursive"}
