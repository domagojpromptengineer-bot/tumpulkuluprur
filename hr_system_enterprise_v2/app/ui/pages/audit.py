import streamlit as st
from ...common.utils import get_conn, query_df

def render(role):
    st.header("Audit Log")
    if role != "admin":
        st.error("Pristup dozvoljen samo za ulogu 'admin'.")
        return

    df = query_df("SELECT * FROM audit_log ORDER BY id DESC LIMIT 500")
    st.dataframe(df, use_container_width=True)
    
    if st.button("Obriši Audit Log"):
        conn = get_conn()
        conn.execute("DELETE FROM audit_log")
        conn.commit()
        conn.close()
        st.success("Zapisnik obrisan.")
        st.rerun()