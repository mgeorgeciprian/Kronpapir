from editorial.geo_scope import scope, other_region_in, mentions_local_place


def test_other_county_from_local_source_is_not_local():
    art = {"title": "Accident grav în Teleorman. O mașină s-a răsturnat, o persoană a decedat",
           "content": "Planul Roșu de Intervenție a fost activat pe DN6."}
    assert scope(art) == "alta_zona"


def test_brasov_mention_wins_over_other_city():
    art = {"title": "Sinaia, Bucureşti şi Braşov, cele mai căutate destinaţii", "content": ""}
    assert scope(art) == "local"


def test_covasna_and_demonym_without_diacritics():
    assert mentions_local_place("Concert la Sfantu Gheorghe")
    assert mentions_local_place("Brașovenii au ieșit la protest")
    assert scope({"title": "Protest în creșe", "content": "Peste 500 de copii din Brasov..."}) == "local"


def test_unknown_when_no_place():
    assert scope({"title": "ANM: ninsori în weekend", "content": "Temperaturi de -10 grade."}) is None


def test_ambiguous_words_do_not_trigger():
    # „albă”, râul Olt, Întorsura Buzăului nu sunt alte județe
    assert other_region_in("Zăpadă albă pe Olt") is None
    assert other_region_in("Drum închis la Întorsura Buzăului") is None
    assert other_region_in("Incendiu în județul Mureș") == "judetul mures"


def test_inflected_and_false_friends():
    assert mentions_local_place("Primăria Brașovului anunță")
    assert mentions_local_place("Drumul Făgărașului")
    assert not mentions_local_place("Nouă spitale din Capitală vor asigura urgențele")
    assert not mentions_local_place("Un brand nou pentru Catalina")
