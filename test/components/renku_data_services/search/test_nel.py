"""Tests for non empty list."""

from renku_data_services.search.nel import Nel


def test_nel() -> None:
    value = Nel(1)
    assert value.to_list() == [1]

    value = Nel(1, [2, 3])
    assert value.to_list() == [1, 2, 3]

    value = Nel.of(1, 2, 3, "a")
    assert value.to_list() == [1, 2, 3, "a"]

    value = Nel.of(1, 2, 3, 4)
    assert value.to_list() == [1, 2, 3, 4]
    assert value.to_set() == set([1, 2, 3, 4])

    value = Nel.of(1, 2).append(Nel.of(3, 4))
    assert value.to_list() == [1, 2, 3, 4]

    nel = Nel.of(1, 2)
    value = nel.append([])
    assert value is nel

    value = nel.append([3, 4])
    assert value.to_list() == [1, 2, 3, 4]

    nel: Nel[int] | None = Nel.from_list([])
    assert nel is None

    nel = Nel.from_list([1, 2, 3])
    assert nel == Nel.of(1, 2, 3)


def test_iteration() -> None:
    nel = Nel.of(1, 2, 3, 4, 5)
    lst1 = [e for e in nel]
    lst2 = [e for e in nel]
    assert lst2 == nel.to_list()
    assert lst1 == lst2

    lst3 = [e for e in Nel.of(1)]
    assert lst3 == [1]

    assert len(nel) == 5
    assert nel[0] == 1
    assert nel[1] == 2

    assert set(nel) == set([1, 2, 3, 4, 5])

    lst = [0, 1]
    lst.extend(nel)
    assert lst == [0, 1, 1, 2, 3, 4, 5]


def test_mk_string() -> None:
    nel = Nel.of(1, 2, 3, 4, 5)
    assert nel.mk_string(",") == "1,2,3,4,5"
    assert Nel.of(1).mk_string(",") == "1"
