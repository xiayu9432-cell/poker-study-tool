class CardStateLayer:
    BOARD_PROGRESSION = {0: {3}, 3: {4, 5}, 4: {5}}

    @classmethod
    def candidate_allowed(cls, field, cards, published, allow_empty=False):
        cards, published = list(cards or ()), list(published or ())
        if field == "heroCards" and published and cards != published:
            return False, "hero_locked"
        if field == "boardCards":
            if published and (not cards or len(cards) < len(published)):
                return False, "board_regression"
            if published and len(cards) == len(published):
                return False, "board_same_street_change"
            if len(cards) not in cls.BOARD_PROGRESSION.get(len(published), set()):
                return False, "board_progression_invalid"
        if not cards and not allow_empty:
            return False, "empty_not_allowed"
        if cards == published:
            return False, "already_published"
        return True, None

    @staticmethod
    def required_frames(field, cards, allow_empty=False):
        if field == "heroCards" and cards:
            return 3
        if allow_empty and not cards:
            return 1
        return 2
