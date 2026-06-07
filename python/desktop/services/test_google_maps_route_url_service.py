#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""google_maps_route_url_service の単体テスト（pytest 不要・直接実行可）"""

from google_maps_route_url_service import (
    ORIGIN_LABEL,
    build_directions_url,
    build_embed_directions_url,
    dedupe_stores_by_coordinates,
    generate_route_map_urls,
    split_into_segments,
    stop_to_path_segment,
)


def _store(code: str, name: str, lat=None, lng=None):
    return {
        "store_code": code,
        "store_name": name,
        "latitude": lat,
        "longitude": lng,
    }


def test_dedupe_same_coordinates():
    stores = [
        _store("HA-14", "ハードオフつくば研究学園店", 36.083, 140.076),
        _store("OH-01", "オフハウスつくば研究学園店", 36.083, 140.076),
        _store("SS-57", "セカンドストリート", 36.1, 140.1),
    ]
    unique, skipped = dedupe_stores_by_coordinates(stores)
    assert len(unique) == 2
    assert len(skipped) == 1
    assert skipped[0].store_code == "OH-01"
    assert skipped[0].kept_store_code == "HA-14"


def test_split_nine_stores():
    stores = [_store(f"S{i:02d}", f"店{i}", 36.0 + i * 0.01, 140.0) for i in range(14)]
    unique, _ = dedupe_stores_by_coordinates(stores)
    chunks = split_into_segments(unique, max_stops=9)
    assert len(chunks) == 2
    assert len(chunks[0]) == 9
    assert len(chunks[1]) == 5


def test_build_directions_url_starts_with_current_location():
    url = build_directions_url([_store("A", "店A", 36.1, 140.1)])
    assert url.startswith("https://www.google.com/maps/dir/Current+Location/")
    assert "36.1,140.1" in url


def test_build_embed_directions_url():
    url = build_embed_directions_url(
        [_store("A", "店A", 36.1, 140.1), _store("B", "店B", 36.2, 140.2)],
        "TEST_KEY",
        origin=ORIGIN_LABEL,
    )
    assert url.startswith("https://www.google.com/maps/embed/v1/directions?")
    assert "key=TEST_KEY" in url
    assert "origin=Current+Location" in url
    assert "destination=36.2%2C140.2" in url or "destination=36.2,140.2" in url
    assert "waypoints=" in url


def test_generate_route_map_urls_segments():
    stores = [_store(f"S{i:02d}", f"店{i}", 36.0 + i * 0.01, 140.0) for i in range(12)]
    result = generate_route_map_urls(stores, api_key="TEST_KEY")
    assert len(result.segments) == 2
    assert result.segments[0].index == 1
    assert len(result.segments[0].store_codes) == 9
    assert len(result.segments[1].store_codes) == 3
    assert result.segments[0].url.startswith("https://www.google.com/maps/dir/Current+Location/")
    assert result.segments[0].embed_url.startswith("https://www.google.com/maps/embed/v1/directions?")


def test_route2_starts_from_route1_end():
    stores = [_store(f"S{i:02d}", f"店{i}", 36.0 + i * 0.01, 140.0) for i in range(12)]
    result = generate_route_map_urls(stores)
    last_of_route1 = stop_to_path_segment(stores[8])
    assert result.segments[1].url.startswith(f"https://www.google.com/maps/dir/{last_of_route1}/")
    assert ORIGIN_LABEL not in result.segments[1].url


def test_store_code_to_segment_includes_skipped_duplicate():
    stores = [
        _store("HA-14", "ハードオフ", 36.083, 140.076),
        _store("OH-01", "オフハウス", 36.083, 140.076),
        _store("SS-57", "SS", 36.1, 140.1),
    ]
    result = generate_route_map_urls(stores)
    assert result.store_code_to_segment["HA-14"] == 1
    assert result.store_code_to_segment["OH-01"] == 1
    assert result.store_code_to_segment["SS-57"] == 1


def test_missing_coordinates_reported():
    stores = [_store("X1", "座標なし店", None, None)]
    result = generate_route_map_urls(stores)
    assert len(result.segments) == 1
    assert len(result.missing_coordinates) == 1
    assert result.missing_coordinates[0]["store_code"] == "X1"


if __name__ == "__main__":
    test_dedupe_same_coordinates()
    test_split_nine_stores()
    test_build_directions_url_starts_with_current_location()
    test_build_embed_directions_url()
    test_generate_route_map_urls_segments()
    test_route2_starts_from_route1_end()
    test_store_code_to_segment_includes_skipped_duplicate()
    test_missing_coordinates_reported()
    print("All tests passed.")
