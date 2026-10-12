import pandas as pd
import pytest
import requests
import responses

from actions_monitor import (
    SSZ_COLOR_SCALE,
    add_badge_url_manually,
    build_conclusion_color_map,
    format_runs_table,
    search_github,
)


def test_build_conclusion_color_map_success_and_failure_fixed():
    color_map = build_conclusion_color_map(["success", "failure"], SSZ_COLOR_SCALE)

    assert color_map["success"] == SSZ_COLOR_SCALE[0]
    assert color_map["failure"] == SSZ_COLOR_SCALE[1]


def test_build_conclusion_color_map_extra_categories_stable():
    conclusions = ["success", "failure", "cancelled", "skipped"]

    first = build_conclusion_color_map(conclusions, SSZ_COLOR_SCALE)
    second = build_conclusion_color_map(list(reversed(conclusions)), SSZ_COLOR_SCALE)

    assert first == second
    assert first["cancelled"] in SSZ_COLOR_SCALE[2:]
    assert first["skipped"] in SSZ_COLOR_SCALE[2:]
    assert first["cancelled"] != first["skipped"]


def test_build_conclusion_color_map_handles_nan():
    color_map = build_conclusion_color_map(
        ["success", "failure", float("nan")],
        SSZ_COLOR_SCALE,
    )

    assert set(color_map.keys()) == {"success", "failure"}


def test_add_badge_url_manually_shape():
    df = pd.DataFrame({"path": [".github/workflows/foo.yml"]})

    result = add_badge_url_manually(df, "OWNER/REPO")

    assert result.loc[0, "yaml_path_manual"] == "workflows/foo.yml"
    assert (
        result.loc[0, "badge_url_manual"]
        == " https://github.com/OWNER/REPO/actions/workflows/foo.yml/badge.svg"
    )


def test_format_runs_table_computes_duration_and_columns():
    runs = pd.DataFrame(
        {
            "name": ["wf1"],
            "head_branch": ["main"],
            "run_number": [1],
            "event": ["push"],
            "status": ["completed"],
            "conclusion": ["success"],
            "run_started_at": ["2026-01-01T10:00:00Z"],
            "html_url": ["https://example.com/run/1"],
            "created_at": ["2026-01-01T10:00:00Z"],
            "updated_at": ["2026-01-01T10:05:30Z"],
            "run_attempt": [1],
        }
    )

    result = format_runs_table(runs)

    expected_cols = {
        "name", "head_branch", "run_number", "event", "status", "conclusion",
        "run_started_at", "html_url", "created_at", "updated_at", "run_duration",
        "run_attempt",
    }
    assert expected_cols.issubset(set(result.columns))
    assert result.loc[0, "run_duration"] == pd.Timedelta(minutes=5, seconds=30)
    assert pd.api.types.is_integer_dtype(runs["conclusion_code"])


@responses.activate
def test_search_github_pagination_yields_all_pages():
    base_url = "https://api.github.com/repos/OWNER/REPO"
    page1_url = f"{base_url}/actions/runs?per_page=100"
    page2_url = f"{base_url}/actions/runs?per_page=100&page=2"

    responses.add(
        responses.GET,
        page1_url,
        json={"workflow_runs": []},
        status=200,
        headers={"Link": f'<{page2_url}>; rel="next"'},
    )
    responses.add(
        responses.GET,
        page2_url,
        json={"workflow_runs": []},
        status=200,
    )

    pages = list(search_github(base_url, "actions/runs", "fake-token"))

    assert len(pages) == 2
    assert pages[0].status_code == 200
    assert pages[1].status_code == 200


@responses.activate
def test_search_github_raises_http_error_on_401():
    base_url = "https://api.github.com/repos/OWNER/REPO"
    responses.add(
        responses.GET,
        f"{base_url}/actions/runs?per_page=100",
        json={"message": "Bad credentials"},
        status=401,
    )

    with pytest.raises(requests.HTTPError):
        list(search_github(base_url, "actions/runs", "bad-token"))
