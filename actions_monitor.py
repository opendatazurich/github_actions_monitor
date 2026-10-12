import logging

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

logger = logging.getLogger(__name__)

# Default color scale from Statistik Stadt Zürich (https://github.com/StatistikStadtZuerich/zuericolors/).
# For non-SSZ deployments, replace with e.g. `px.colors.qualitative.G10`.
SSZ_COLOR_SCALE = ("#3431DE", "#DB247D", "#1F9E31", "#FBB900", "#23C3F1", "#FF720C")
COLOR_SCALE = SSZ_COLOR_SCALE


def search_github(base_url, url_add, access_token, per_page=100):
    """Yield response pages from a paginated GitHub API endpoint."""
    session = requests.Session()
    url = f"{base_url}/{url_add}?per_page={per_page}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {access_token}",
    }
    first_page = session.get(url, headers=headers)
    first_page.raise_for_status()
    yield first_page

    next_page = first_page
    while get_next_page(next_page) is not None:
        try:
            next_page_url = next_page.links["next"]["url"]
            next_page = session.get(next_page_url, headers=headers)
            next_page.raise_for_status()
            yield next_page
        except KeyError:
            logger.debug("No more GitHub pages")
            break


def get_next_page(page):
    return page if page.headers.get("link") is not None else None


@st.cache_data(ttl=300)
def get_workflowlist(base_url, _access_token):
    """Return the full list of workflows for the configured repo as a DataFrame."""
    df = pd.DataFrame()
    for page in search_github(base_url, "actions/workflows", _access_token):
        logger.debug("workflows page: %s", page)
        df_page = pd.DataFrame(page.json()["workflows"])
        logger.debug("row count: %d", df_page.shape[0])
        df = pd.concat([df, df_page], ignore_index=True)
    return df


def add_badge_url_manually(df, repo):
    """Compose the status badge URL for each workflow row."""
    df["yaml_path_manual"] = df["path"].str.split("/", n=1, expand=True)[1]
    df["badge_url_manual"] = (
        " https://github.com/" + repo + "/actions/" + df["yaml_path_manual"] + "/badge.svg"
    )
    return df


def format_workflow_table(wft, repo):
    """Select and prepare workflow columns for display."""
    wft = add_badge_url_manually(wft, repo)
    cols = ["badge_url_manual", "name", "state", "created_at", "updated_at", "html_url"]
    return wft[cols]


@st.cache_data(ttl=300)
def get_runs_list(base_url, _access_token, page_max=1000, per_page=100):
    """Return workflow runs as a DataFrame, limited to page_max entries."""
    no_pages = page_max / per_page
    runs = pd.DataFrame()
    ctr = 1
    for page in search_github(base_url, "actions/runs", _access_token, per_page):
        logger.debug("runs page: %s", page)
        df_page = pd.DataFrame(page.json()["workflow_runs"])
        logger.debug("row count: %d", df_page.shape[0])
        runs = pd.concat([runs, df_page], ignore_index=True)

        ctr += 1
        if ctr > no_pages:
            break

    return runs


def format_runs_table(runs):
    """Add derived columns (duration, numeric conclusion) and select display columns."""
    runs["conclusion"] = pd.Categorical(runs["conclusion"])
    runs["conclusion_code"] = runs["conclusion"].cat.codes

    runs["run_started_at"] = pd.to_datetime(runs["run_started_at"])
    runs["updated_at"] = pd.to_datetime(runs["updated_at"])
    runs["run_duration"] = runs["updated_at"] - runs["run_started_at"]

    runs["run_url"] = '<a href="' + runs["html_url"] + '">Github url</a>'

    cols = [
        "name", "head_branch", "run_number", "event", "status", "conclusion",
        "run_started_at", "html_url", "created_at", "updated_at", "run_duration",
        "run_attempt",
    ]
    return runs[cols]


def plot_mean_duration(runs):
    df = runs.groupby(["name"]).agg(mean_run_duration=("run_duration", "mean"))
    df = df.sort_values("mean_run_duration", ascending=False)
    df["mean_run_duration_sec"] = df["mean_run_duration"].dt.total_seconds()
    df = df.reset_index()
    fig = px.bar(
        df,
        x="name",
        y="mean_run_duration_sec",
        color_discrete_sequence=COLOR_SCALE,
        title="Durchschnittliche Laufdauer je Workflow in Sekunden",
    )
    return fig


def plot_runs_conclusion(runs):
    """Scatter plot of completed runs over time, colored by conclusion."""
    runs_completed = runs[runs["status"] == "completed"]
    color_map = build_conclusion_color_map(runs_completed["conclusion"], COLOR_SCALE)

    fig = px.scatter(
        runs_completed,
        x="run_started_at", y="name",
        color="conclusion", symbol="conclusion",
        color_discrete_map=color_map,
        hover_data=["run_url"],
        title="Runs mit Status completed",
        height=700,
    )
    return fig


def plot_runs_pie(runs):
    """Pie chart of conclusion distribution."""
    color_map = build_conclusion_color_map(runs["conclusion"], COLOR_SCALE)
    fig = px.pie(
        runs["conclusion"].value_counts(normalize=True).reset_index(),
        color="conclusion",
        color_discrete_map=color_map,
        values="proportion", names="conclusion",
        title="Erfolgsquote der ausgewählten Ergebnisse",
        width=500,
    )
    return fig


def plot_event_pie(runs):
    """Pie chart of runs by trigger event."""
    fig = px.pie(
        runs["event"].value_counts(normalize=True).reset_index(),
        color_discrete_sequence=COLOR_SCALE,
        values="proportion", names="event",
        title="Verteilung nach Eventtrigger",
        width=500,
    )
    return fig


def plot_branch_pie(runs):
    """Pie chart of runs by head branch."""
    fig = px.pie(
        runs["head_branch"].value_counts(normalize=True).reset_index(),
        color_discrete_sequence=COLOR_SCALE,
        values="proportion", names="head_branch",
        title="Verteilung nach Branch",
        width=500,
    )
    return fig


def build_conclusion_color_map(conclusions, base_scale):
    """Build a stable color map for GitHub Actions conclusion values.

    "success" always maps to the first color, "failure" to the second;
    remaining categories cycle through the rest of the scale.
    """
    fixed = {
        "success": base_scale[0],
        "failure": base_scale[1],
    }

    remaining = sorted({str(c) for c in conclusions if pd.notna(c)} - fixed.keys())
    extra_colors = base_scale[2:]
    dynamic = {
        key: extra_colors[i % len(extra_colors)]
        for i, key in enumerate(remaining)
    }

    return fixed | dynamic


def main():
    for key in ("ACCESS_TOKEN", "REPO"):
        if key not in st.secrets:
            st.error(
                f"Secret '{key}' fehlt. Bitte .streamlit/secrets.toml ergänzen "
                "(siehe .streamlit/secrets.toml.example)."
            )
            st.stop()

    access_token = st.secrets["ACCESS_TOKEN"]
    repo = st.secrets["REPO"]
    base_url = f"https://api.github.com/repos/{repo}"

    st.set_page_config("Monitor Github Actions", layout="wide")
    st.title("Github Actions Monitor")
    st.markdown(f"Monitoring für Github Actions Pipelines von https://github.com/{repo}")

    tab1, tab2 = st.tabs(["Übersicht", "Details"])

    with tab1:
        st.markdown("""# Aktueller Status""")
        try:
            wft = get_workflowlist(base_url, access_token)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            st.error(
                f"Zugriff auf Workflows fehlgeschlagen (HTTP {status}). "
                "Bitte Token und Repo prüfen."
            )
            st.stop()

        formatted_wft = format_workflow_table(wft, repo)

        st.data_editor(
            formatted_wft,
            column_config={
                "badge_url_manual": st.column_config.ImageColumn(
                    label="Status Badge",
                    width="large",
                ),
                "html_url": st.column_config.LinkColumn(label="yaml_url"),
            },
            hide_index=True,
            height=35 * len(formatted_wft) + 38,  # hack for showing all rows
        )

    with tab2:
        page_max = st.select_slider(
            "Anzahl Ergebnisse (je mehr desto länger geht's)",
            value=500,
            options=[100, 200, 300, 500, 1000, 2000],
        )

        with st.spinner("Lade Daten..."):
            try:
                runs = get_runs_list(base_url, access_token, page_max=page_max, per_page=100)
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else "?"
                st.error(
                    f"Zugriff auf Runs fehlgeschlagen (HTTP {status}). "
                    "Bitte Token und Repo prüfen."
                )
                st.stop()

            formatted_runs = format_runs_table(runs)

        st.markdown("""# Anteile""")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.plotly_chart(plot_runs_pie(runs))
        with col2:
            st.plotly_chart(plot_event_pie(runs))
        with col3:
            st.plotly_chart(plot_branch_pie(runs))

        st.markdown("""# Rechenzeit""")
        st.plotly_chart(plot_mean_duration(runs))

        st.markdown("""# Zeitreihe""")
        st.plotly_chart(plot_runs_conclusion(runs))

        st.markdown("""# Failure""")
        st.data_editor(
            formatted_runs[formatted_runs["conclusion"] == "failure"],
            hide_index=True,
            key="failure",
            column_config={"html_url": st.column_config.LinkColumn()},
        )

        st.markdown("""# Noch am Laufen""")
        st.data_editor(
            formatted_runs[formatted_runs["status"] != "completed"],
            hide_index=True,
            key="running",
            column_config={"html_url": st.column_config.LinkColumn()},
        )

        st.markdown("""# Alle Daten""")
        st.data_editor(
            formatted_runs,
            hide_index=True,
            key="all",
            column_config={"html_url": st.column_config.LinkColumn()},
        )


if __name__ == "__main__":
    main()
