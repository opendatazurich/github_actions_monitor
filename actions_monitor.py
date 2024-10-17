import streamlit as st

import requests
import pandas as pd
import plotly.express as px

# constants an setup
access_token = st.secrets["ACCESS_TOKEN"]
repo = st.secrets["REPO"]
base_url = f'https://api.github.com/repos/{repo}'
ssz_color_scale = ("#3431DE", "#DB247D", "#1F9E31", "#FBB900", "#23C3F1", "#FF720C") # source https://github.com/StatistikStadtZuerich/zuericolors/
color_scale = ssz_color_scale # alternative px.colors.qualitative.G10


#functions
def search_github(base_url, url_add, per_page = 100):
    """
    Query paginated github url
    """
    session = requests.Session()

    url = f'{base_url}/{url_add}?per_page={per_page}'
    
    headers = {"Accept": "application/vnd.github+json",'Authorization': "Bearer {}".format(access_token)}
    first_page = session.get(url, headers=headers)
    yield first_page
    
    next_page = first_page
    while get_next_page(next_page) is not None:  
        try:
            next_page_url = next_page.links['next']['url']
            next_page = session.get(next_page_url, headers=headers)
            yield next_page
        
        except KeyError:
            print("No more Github pages")
            break
            
def get_next_page(page):
    return page if page.headers.get('link') != None else None

def get_workflowlist(base_url):
    """
    Query github api to get list of workflows
    """
    # Iterate through pages
    df = pd.DataFrame()
    for page in search_github(base_url, 'actions/workflows'):
        print('workflows page', page)
        df_page = pd.DataFrame(page.json()['workflows'])
        print("Antahl Zeilen:", df_page.shape[0])
        df = df._append(df_page)
    return df

def add_badge_url_manually(df):
    """
    Compose Badge URL manually. Takes and return pandas df
    """
    # aufarbeitung path spalte
    df['yaml_path_manual'] = df['path'].str.split("/", n=1, expand=True)[1]
    # neue Spalte zusammensetzen
    df['badge_url_manual'] = " https://github.com/" + repo + "/actions/" + df['yaml_path_manual'] + "/badge.svg"

    return df


def format_workflow_table(wft):
    """
    Format pandas df
    """
    wft = add_badge_url_manually(wft)
    cols = ['badge_url_manual', 'name', 'state', 'created_at', 'updated_at', 'html_url'] # 'badge_url',
    # wft['created_at'] = pd.to_datetime(wft['created_at'], utc=True).dt.strftime('%Y-%m-%d %H:%M:%S')
    # wft['updated_at'] = pd.to_datetime(wft['updated_at'], utc=True)
    return wft[cols]

def get_runs_list(page_max = 1000, per_page = 100):
    """
    Query github api to get list of runs
    :per_page number of entries per page in api (max is 100)
    :page_max number of runs you want in the end (query end if this is reached)
    """

    no_pages = page_max/per_page

    # Iterate through pages
    runs = pd.DataFrame()
    ctr = 1
    for page in search_github(base_url, 'actions/runs', per_page):
        print(page)
        df_page = pd.DataFrame(page.json()['workflow_runs'])
        print("Antahl Zeilen:", df_page.shape[0])
        runs = runs._append(df_page)

        ctr += 1
        if ctr > no_pages:
            break
    
    return runs

def format_runs_table(runs):
    """Format pandas df"""

    # get numerical values for conclusion
    runs['conclusion'] = pd.Categorical(runs['conclusion'])
    runs['conclusion_code'] = runs['conclusion'].cat.codes

    runs['run_started_at'] = pd.to_datetime(runs['run_started_at'])
    runs['updated_at'] = pd.to_datetime(runs['updated_at'])
    runs['run_duration'] = runs['updated_at'] - runs['run_started_at']

    runs['run_url'] = '''<a href=\"''' + runs['html_url']+'''\">Github url</a>'''

    cols = ['name','head_branch','run_number','event','status','conclusion','run_started_at','html_url','created_at','updated_at','run_duration','run_attempt']

    return runs[cols]

def plot_mean_duration(runs):

    df = runs.groupby(['name']).agg(
        mean_run_duration = ('run_duration', 'mean')
    )
    df = df.sort_values('mean_run_duration', ascending=False)
    df['mean_run_duration_sec'] = df['mean_run_duration'].dt.total_seconds() # output in seconds
    df = df.reset_index()
    fig = px.bar(df, x='name', y='mean_run_duration_sec', 
                 color_discrete_sequence=color_scale,
                 title='Durschnittlische Laufdauer je Workflow in Sekunden')
    return fig

def plot_runs_conclusion(runs):
    """
    returns plotly sactter fig from pandas df
    """
    fig = px.scatter(runs[runs['status']=='completed'], 
                     x='run_started_at', y='name', 
                     color='conclusion', symbol='conclusion',
                     color_discrete_sequence=color_scale,#px.colors.qualitative.G10,
                     hover_data=['run_url'],
                     title='Runs mit Status completed',
                     height=700,
                     )
    return fig

def plot_runs_pie(runs):
    """
    returns plotly pie fig from pandas df
    """
    fig = px.pie(
        runs['conclusion'].value_counts(normalize=True).reset_index(), 
        color_discrete_sequence=color_scale,#px.colors.qualitative.G10,
        values='proportion', names='conclusion', title='Erfolgsquote der ausgewählten Ergebnisse',
        width=500)
    return fig

def plot_event_pie(runs):
    """
    returns plotly pie fig from pandas df
    """
    fig = px.pie(
        runs['event'].value_counts(normalize=True).reset_index(), 
        color_discrete_sequence=color_scale,#px.colors.qualitative.G10,
        values='proportion', names='event', title='Verteilung nach Eventtrigger',
        width=500)
    return fig

def plot_branch_pie(runs):
    """
    returns plotly pie fig from pandas df
    """
    fig = px.pie(
        runs['head_branch'].value_counts(normalize=True).reset_index(), 
        color_discrete_sequence=color_scale,#px.colors.qualitative.G10,
        values='proportion', names='head_branch', title='Verteilung nach Branch',
        width=500)
    return fig


############# The App

st.set_page_config('Monitor Github Actions', layout="wide")
st.title('Github Actions Monitor')

st.markdown(f"""Monitoring für Github Actions Pipelines von https://github.com/{repo}""")

tab1, tab2 = st.tabs(["Übersicht", "Details"])

with tab1:
    st.markdown("""# Aktueller Status""")
    wft = get_workflowlist(base_url)
    formatted_wft = format_workflow_table(wft)

    st.data_editor(
        formatted_wft,
        column_config={
            "badge_url": st.column_config.ImageColumn(
                label="Status Badge", 
                # help="Streamlit app preview screenshots",
                width='large',
            ),
            "badge_url_manual": st.column_config.ImageColumn(
                label="Status Badge", 
                # help="Streamlit app preview screenshots",
                width='large',
            ),
            'html_url': st.column_config.LinkColumn(
                label='yaml_url',
            ),
        },
        hide_index=True,
        height=35*len(formatted_wft)+38, # hack fpr showing all rows
    )


with tab2:
    page_max = st.select_slider(
        "Anzahl Ergebnisse (je mehr desto länger geht's)",
        value=500,
        options=[100,200,300,500,1000,2000],
    )

    with st.spinner('Lade Daten...'):
        runs = get_runs_list(page_max = page_max, per_page = 100)

        formatted_runs = format_runs_table(runs)
    
    st.markdown("""# Anteile""")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.plotly_chart(plot_runs_pie(runs))
    with col2:
        st.plotly_chart(plot_event_pie(runs))
    with col3:
        st.plotly_chart(plot_branch_pie(runs))
    
    st.markdown(f"""# Rechenzeit""")
    st.plotly_chart(plot_mean_duration(runs))

    st.markdown(f"""# Zeitreihe""")
    st.plotly_chart(plot_runs_conclusion(runs))
    
    st.markdown("""# Failure""")
    st.data_editor(formatted_runs[formatted_runs['conclusion']=='failure'], 
                    hide_index=True,
                    key='failure',
                    column_config={
                        'html_url': st.column_config.LinkColumn(),
                    },)
    
    st.markdown("""# Noch am Laufen""")
    st.data_editor(formatted_runs[formatted_runs['status']!='completed'], 
                    hide_index=True,
                    key='running',
                    column_config={'html_url': st.column_config.LinkColumn(), },
                   )
    
    st.markdown("""# Alle Daten""")
    st.data_editor(formatted_runs, 
                    hide_index=True,
                    key='all',
                    column_config={'html_url': st.column_config.LinkColumn(), },
                   )
    
