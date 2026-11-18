from card_state_layer import CardStateLayer


def test_card_publish_rules_are_explicit():
    assert CardStateLayer.required_frames("heroCards", ["As", "Kh"]) == 3
    assert CardStateLayer.candidate_allowed("heroCards", ["As", "Qh"], ["As", "Kh"])[1] == "hero_locked"
    assert CardStateLayer.candidate_allowed("boardCards", ["2c", "3d", "4h", "5s"],
                                            ["2c", "3d", "4h"])[0]
    assert CardStateLayer.candidate_allowed("boardCards", ["2c", "3d", "4h"],
                                            ["2c", "3d", "4h", "5s"])[1] == "board_regression"


if __name__ == "__main__":
    test_card_publish_rules_are_explicit()
    print("card state layer tests passed")
