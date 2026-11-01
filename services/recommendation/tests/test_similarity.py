from recommendation.similarity import Item, VectorCache, feature_vector, rank

ITEMS = [
    Item("TENT-2P", ("camping", "shelter")),
    Item("TENT-4P", ("camping", "shelter")),
    Item("STOVE-CAN", ("camping", "kitchen")),
    Item("JACKET-RAIN", ("clothing",)),
]


def test_vectors_are_deterministic_and_normalized() -> None:
    a = feature_vector(ITEMS[0])

    assert a == feature_vector(ITEMS[0])
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9


def test_products_sharing_categories_rank_first() -> None:
    vectors = {i.id: feature_vector(i) for i in ITEMS}

    assert rank("TENT-2P", vectors, limit=3) == ["TENT-4P", "STOVE-CAN", "JACKET-RAIN"]


def test_v1_cache_holds_one_entry() -> None:
    cache = VectorCache("v1")
    cache.vectors(ITEMS, "s1", "TENT-2P")
    cache.vectors(ITEMS, "s2", "TENT-4P")

    assert len(cache) == 1
