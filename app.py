"""OSCA Streamlit entrypoint: branded election-night viewer with bidirectional SOS refresh."""
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from election_night.sos import pull

ROOT=Path(__file__).resolve().parent
FRONTEND=ROOT/'election_night'/'frontend'
st.set_page_config(page_title='OSCA - Open-Source Campaign Analytics',
    page_icon=str(FRONTEND/'assets'/'oscar_baby_icon_rose_crop.png'),layout='wide',initial_sidebar_state='collapsed')
st.markdown('''<style>
 .stMainBlockContainer{padding:0.8rem 1rem 1rem;max-width:none}
 [data-testid="stAppViewContainer"]{background:#0e1117}
 [data-testid="stHeader"]{background:transparent}
 [data-testid="stToolbar"]{opacity:.7}
 iframe[title="election_night.osca_viewer"]{border:0}
 </style>''',unsafe_allow_html=True)

viewer=components.declare_component('osca_viewer',path=str(FRONTEND))

@st.cache_data(ttl=45,show_spinner=False)
def fetch_sos():
    return pull(2026)

demo=str(st.query_params.get('demo','0'))=='1'
request=viewer(demo=demo,sos_response=st.session_state.get('osca_sos_response'),
    key='osca_election_night_v2',default=None)

if isinstance(request,dict):
    request_id=request.get('requestId')
    if isinstance(request_id,str) and len(request_id)<100 and request_id!=st.session_state.get('osca_last_request'):
        st.session_state.osca_last_request=request_id
        if request.get('action')=='mode':
            st.query_params['demo']='1' if request.get('demo') else '0'
            st.rerun()
        elif request.get('action')=='sos' and not demo:
            try:
                with st.spinner('Reading official Vermont SOS results…'):
                    data=fetch_sos()
                st.session_state.osca_sos_response={'requestId':request_id,'data':data}
            except Exception as exc:
                st.session_state.osca_sos_response={'requestId':request_id,'error':f'SOS refresh unavailable: {exc}'}
            st.rerun()
