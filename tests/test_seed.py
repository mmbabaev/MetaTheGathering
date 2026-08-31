from core.models import Archetype
from utils.seed import PAUPER_ARCHETYPES, seed


class TestSeed:
    def test_seeds_all_archetypes(self, db):
        added = seed(db)
        assert added == len(PAUPER_ARCHETYPES)

    def test_idempotent(self, db):
        seed(db)
        added_second = seed(db)
        assert added_second == 0

    def test_no_duplicates_in_db(self, db):
        seed(db)
        seed(db)
        count = db.query(Archetype).count()
        assert count == len(PAUPER_ARCHETYPES)

    def test_archetype_names_correct(self, db):
        seed(db)
        names = {a.name for a in db.query(Archetype).all()}
        expected = {a["name"] for a in PAUPER_ARCHETYPES}
        assert names == expected

    def test_seed_does_not_overwrite_weekly_meta_rank(self, db):
        seed(db)
        archetype = db.query(Archetype).filter_by(name="Blue Terror").one()
        archetype.meta_rank = 7
        db.commit()

        seed(db)

        assert archetype.meta_rank == 7
