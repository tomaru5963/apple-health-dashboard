import base64
from datetime import timedelta
from enum import Enum
import io
from pathlib import Path
from typing import NamedTuple, Optional
import zipfile

from dash import callback, Dash, dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from flask import g
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


class TimeRange(NamedTuple):
    label: str
    value: int
    delta: Optional[timedelta] = None


TIME_RANGE_TABLE = [
        TimeRange('Entire duration', -1),
        TimeRange('One year', 1, timedelta(days=365)),
        TimeRange('Six months', 2, timedelta(days=183)),
        TimeRange('One month', 3, timedelta(days=31)),
]


RecordType = Enum('RecordType',
                  [('SBP', 'HKQuantityTypeIdentifierBloodPressureSystolic'),
                   ('DBP', 'HKQuantityTypeIdentifierBloodPressureDiastolic'),
                   ('HR', 'HKQuantityTypeIdentifierHeartRate'),
                   ('BM', 'HKQuantityTypeIdentifierBodyMass')])


app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
LAST_DATA_PATH = Path(app.server.instance_path) / 'df.pkl'


@app.server.teardown_appcontext
def teardown_df(exception):
    df = g.pop('df', None)

    if df is not None:
        df.to_pickle(LAST_DATA_PATH)


file_upload = dcc.Upload(
        dbc.Button('Drag and Drop or Select a File',
                   color='light',
                   className='p-4 border'),
        id='upload-data',
        className='d-grid gap-2, mt-3'
)


time_range = html.Div(
    [
        dbc.Label('Period of time'),
        dbc.RadioItems(
            options=[
                {'label': tr.label, 'value': tr.value}
                for tr in TIME_RANGE_TABLE
            ],
            value=TIME_RANGE_TABLE[0].value,
            id='time-range-input',
            inline=True,
        ),
    ]
)


@callback(Output('output-graph', 'children'),
          Output('output-table', 'children'),
          Input('upload-data', 'contents'),
          State('upload-data', 'filename'),
          State('upload-data', 'last_modified'),
          Input('time-range-input', 'value'))
def update_output(contents, filename, date, time_range):
    df = parse_contents(contents, filename, date)
    if df is not None:
        g.df = df
    elif 'df' not in g:
        if LAST_DATA_PATH.exists():
            g.df = pd.read_pickle(LAST_DATA_PATH)
        else:
            return None, None

    start_date = g.df['startDate'].min()
    last_date = g.df['startDate'].max()
    for tr in TIME_RANGE_TABLE:
        if time_range == tr.value:
            break
    else:
        assert False, 'Invalid time_range value'
    if tr.delta is not None:
        start_date = last_date - tr.delta
        start_date = start_date.replace(hour=0, minute=0, second=0,
                                        microsecond=0, nanosecond=0)
    df = g.df[g.df['startDate'] >= start_date]
    return build_graph(df), build_table(df)


def parse_contents(contents, filename, date):
    if contents is None:
        return None

    content_type, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    with zipfile.ZipFile(io.BytesIO(decoded)) as zip_:
        xml_path = zipfile.Path(zip_, at='apple_health_export/export.xml')
        if not xml_path.exists():
            return None
        with xml_path.open() as xml:
            df = pd.read_xml(
                    xml,
                    xpath=('/HealthData/Record['
                           f'@type="{RecordType.SBP.value}" or '
                           f'@type="{RecordType.DBP.value}" or '
                           f'@type="{RecordType.HR.value}" or '
                           f'@type="{RecordType.BM.value}"'
                           ']'),
                    parse_dates=['creationDate', 'startDate', 'endDate']
            )
    df['date'] = df['startDate'].dt.strftime('%Y-%m-%d')
    return df


# https://megatenpa.com/python/plotly/go/go-subplot/
# https://megatenpa.com/python/plotly/go/go-subplot/
def build_graph(df):
    df_bp = df.query(f'type == "{RecordType.SBP.value}" or '
                     f'type == "{RecordType.DBP.value}"')
    graph_bp = go.Box(x=df_bp['startDate'], y=df_bp['value'],
                      name='BP', yaxis='y1')
    df_hr = df.query(f'type == "{RecordType.HR.value}"')
    graph_hr = go.Scatter(x=df_hr['startDate'], y=df_hr['value'],
                          name='HR', yaxis='y2')
    df_bm = df.query(f'type == "{RecordType.BM.value}"')
    graph_bm = go.Scatter(x=df_bm['startDate'], y=df_bm['value'],
                          name='BM')

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        specs=[[{'rowspan': 2, 'secondary_y': True}],
                               [None],
                               [{'secondary_y': False}]])
    fig.add_trace(graph_bp, 1, 1, secondary_y=False)
    fig.add_trace(graph_hr, 1, 1, secondary_y=True)
    fig.add_trace(graph_bm, 3, 1)

    layout = go.Layout(
            legend=dict(
                yanchor="top",
                y=0.99,
                xanchor="left",
                x=0.01),
            margin=dict(r=0),
            xaxis=dict(title='Date'),
            yaxis=dict(title='BP [mmHg]', side='left'),
            yaxis2=dict(title='HR [bpm]', side='right'),
            yaxis3=dict(title='BM [kg]', side='left')
    )
    fig['layout'].update(layout)
    fig.add_hline(y=120, line_width=1, line_dash='dash', row=1, col=1)
    fig.add_hline(y=80, line_width=1, line_dash='dash', row=1, col=1)

    return dcc.Graph(figure=fig)


def build_graph_alt():
    df = g.df
    df_bp = df.query(f'type == "{RecordType.SBP.value}" or '
                     f'type == "{RecordType.DBP.value}"')
    graph_bp = go.Box(x=df_bp['startDate'], y=df_bp['value'],
                      name='BP', yaxis='y1')
    df_hr = df.query(f'type == "{RecordType.HR.value}"')
    graph_hr = go.Scatter(x=df_hr['startDate'], y=df_hr['value'],
                          name='HR', yaxis='y2')
    df_bm = df.query(f'type == "{RecordType.BM.value}"')
    graph_bm = go.Scatter(x=df_bm['startDate'], y=df_bm['value'],
                          name='BM', yaxis='y2')

    layout = go.Layout(
            xaxis=dict(title='Date'),
            yaxis1=dict(title='BP [mmHg]', side='left'),
            yaxis2=dict(title='HR [bpm]', side='right', overlaying='y')
    )

    fig = go.Figure(data=[graph_bp, graph_hr, graph_bm], layout=layout)
    fig.add_hline(y=120, line_width=1, line_dash='dash')
    fig.add_hline(y=80, line_width=1, line_dash='dash')

    return dcc.Graph(figure=fig)


def build_graph_alt2():
    df = g.df
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    df_bp = df.query(f'type == "{RecordType.SBP.value}" or '
                     f'type == "{RecordType.DBP.value}"')
    graph_bp = go.Box(x=df_bp['startDate'], y=df_bp['value'], name='BP')
    fig.add_trace(graph_bp, secondary_y=False)
    df_hr = df.query(f'type == "{RecordType.HR.value}"')
    graph_hr = go.Scatter(x=df_hr['startDate'], y=df_hr['value'], name='HR')
    fig.add_trace(graph_hr, secondary_y=True)

    fig.update_xaxes(title_text='Date')
    fig.update_yaxes(title_text='BP [mmHg]', secondary_y=False)
    fig.update_yaxes(title_text='HR [bpm]', secondary_y=True)

    return dcc.Graph(figure=fig)


def build_table(df):
    df_pivot = df.pivot(
            index='date', columns='type', values='value'
    ).reset_index()
    df_pivot.columns = df_pivot.columns.to_list()
    df_pivot.rename(columns={'date': 'Date',
                             RecordType.SBP.value: 'SBP',
                             RecordType.DBP.value: 'DBP',
                             RecordType.HR.value: 'HR',
                             RecordType.BM.value: 'BM'},
                    inplace=True)
    df_pivot = df_pivot.reindex(columns=['Date', 'SBP', 'DBP', 'HR', 'BM'])
    table = dbc.Table.from_dataframe(
            df_pivot, striped=True, bordered=True, hover=True
    )
    return table


app.layout = dbc.Container(
        [
            dbc.Row(dbc.Col(file_upload)),
            dbc.Row(dbc.Col(time_range)),
            dbc.Row(dbc.Col(html.Div(id='output-graph'))),
            dbc.Row([dbc.Col(width=1),
                     dbc.Col(html.Div(id='output-table'), width=4)]),
        ],
        fluid=True
)
