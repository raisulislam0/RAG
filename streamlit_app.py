
import streamlit as st
import ollama
from time import time, sleep
from uuid import uuid4 
from random import random
import sqlite3
import os

# Get Ollama URL from environment variable or default to localhost
OLLAMA_URL = os.environ.get('OLLAMA', 'http://localhost:11434')
# Configure Ollama client with the correct URL
ollama.host = OLLAMA_URL
print(f"Connecting to Ollama at: {OLLAMA_URL}")

from processor import is_repetitive_input, embed_text, build_collection
import queue_manager as qm

st.set_page_config(
    page_title="Fiftytwo AI Help",
    layout="centered",
    initial_sidebar_state="collapsed"
)


if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid4())

if 'stop_requested' not in st.session_state:
    st.session_state.stop_requested = False

if 'is_processing' not in st.session_state:
    st.session_state.is_processing = False

if 'last_activity' not in st.session_state:
    st.session_state.last_activity = time()

if 'last_queue_check' not in st.session_state:
    st.session_state.last_queue_check = time()

if 'query_history' not in st.session_state:
    st.session_state.query_history = []

if 'history_exist' not in st.session_state:
    st.session_state.history_exist = False

if 'history_enabled' not in st.session_state:
    st.session_state.history_enabled = False


if 'current_response' not in st.session_state:
    st.session_state.current_response = {"query": "", "response": "", "sources": []}

if 'top_k' not in st.session_state:
    st.session_state.top_k = 1

if 'done' not in st.session_state:
    st.session_state.done = False

current_pos = qm.get_queue_position(st.session_state.session_id)

def request_stop():
    """Set the stop flag to true and handle cleanup"""
    st.session_state.stop_requested = True

def reset_state():
    """Reset the generation state"""
    st.session_state.stop_requested = False
    st.session_state.is_processing = False

def release_and_dequeue():
    """Release the lock and dequeue the session"""
    qm.release_lock(st.session_state.session_id)
    qm.dequeue_query(st.session_state.session_id)

def handle_stop_and_restart(status_container, force_restart=False):
    """Handle stopping processing and interrupting Ollama if needed.

    Args:
        status_container: Streamlit container for status messages
        force_restart: If True, force interrupt Ollama even if there are active queries
    """
    reset_state()
    queue_length = qm.get_queue_length()
    lock_holder = qm.get_lock_holder()
    other_active_queries = (queue_length > 0 and qm.get_queue_position(st.session_state.session_id) == -1) or \
                           (lock_holder and lock_holder != st.session_state.session_id)

    if not other_active_queries or force_restart:
        qm.interrupt_ollama()  # Send SIGINT to Ollama
        status_container.empty()
    else:
        status_container.empty()

def check_stale_sessions():
    """Check for and clean up stale sessions"""
    current_time = time()
    if current_time - st.session_state.last_activity > 3:
        if 'session_id' in st.session_state:
            qm.dequeue_query(st.session_state.session_id)
            qm.release_lock(st.session_state.session_id)
        reset_state()
        st.session_state.last_activity = current_time
    st.session_state.last_activity = current_time
    qm.clean_stale_sessions()

def ensure_ollama_fresh_start():
    """Ensure Ollama is running when needed"""
    queue_length = qm.get_queue_length()
    lock_holder = qm.get_lock_holder()
    if queue_length > 0 or lock_holder:
        qm.ensure_ollama_running()

def response_history_database(session_id=None, query=None, full_response=None):
    conn = sqlite3.connect('response_history.db')
    c = conn.cursor()
    
    # Create table if it doesn't exist
    c.execute('''CREATE TABLE IF NOT EXISTS responses
                 (session_id, query text, response text, timestamp INTEGER)''')
    
    # Store query response if parameters are provided
    if session_id and query and full_response:
        current_time = int(time())
        c.execute('INSERT INTO responses (session_id, query, response, timestamp) VALUES (?, ?, ?, ?)',
                  (session_id, query, full_response, current_time))
    
    conn.commit()
    conn.close()

def retrieve_history_context(session_id):
    conn = sqlite3.connect('response_history.db')
    c = conn.cursor()
    
    c.execute('SELECT query, response FROM responses WHERE session_id = ? ORDER BY rowid DESC LIMIT 5', (session_id,))
    history = c.fetchall()
    
    conn.close()
    return history

def cleanup_history_database():
    """Remove history entries older than 8 hours"""
    conn = sqlite3.connect('response_history.db')
    c = conn.cursor()
    
    # Add timestamp column if it doesn't exist
    try:
        c.execute("SELECT timestamp FROM responses LIMIT 1")
    except sqlite3.OperationalError:
        # Column doesn't exist, add it
        c.execute("ALTER TABLE responses ADD COLUMN timestamp INTEGER DEFAULT 0")
        # Update existing rows with current timestamp
        current_time = int(time())
        c.execute("UPDATE responses SET timestamp = ? WHERE timestamp = 0", (current_time,))
        conn.commit()
    
    # Calculate cutoff time (8 hours ago)
    eight_hours_ago = int(time()) - (8 * 60 * 60)
    
    # Delete entries older than 8 hours
    c.execute("DELETE FROM responses WHERE timestamp < ?", (eight_hours_ago,))
    deleted_count = c.rowcount
    
    conn.commit()
    conn.close()
    
    return deleted_count

def delete_history_item(session_id, query):
    """Delete a specific history item from the database"""
    conn = sqlite3.connect('response_history.db')
    c = conn.cursor()
    
    c.execute('DELETE FROM responses WHERE session_id = ? AND query = ?', (session_id, query))
    
    conn.commit()
    conn.close()




def main():
    
    ensure_ollama_fresh_start()
    check_stale_sessions()
    current_time = time()
    
    if 'last_db_cleanup' not in st.session_state:
        st.session_state.last_db_cleanup = current_time
    
    if current_time - st.session_state.last_db_cleanup > 28800:  # 8 hours in seconds
        cleanup_count = cleanup_history_database()
        st.session_state.last_db_cleanup = current_time
        print(f"Database cleanup: removed {cleanup_count} old history entries")
    
    if current_time - st.session_state.last_queue_check > 10:
        st.session_state.last_queue_check = current_time
        qm.clean_stale_sessions()
        qm.process_next_in_queue()

    with st.sidebar:
        st.title("Response History")
        if st.session_state.query_history:
            for i, item in enumerate(reversed(st.session_state.query_history)):
                col1, col2 = st.columns([9, 1])
                with col1:
                    with st.expander(f"**{item['query']}**"):
                        st.markdown(f"**Response:** {item['response']}")
                        st.markdown("**Sources:**")
                        for url in item['sources']:
                            st.markdown(f"- {url}")
                with col2:
                    # Create a unique key for each delete button
                    disable_status = False
                    if st.session_state.is_processing:
                        disable_status = True   
                    delete_key = f"delete_history_{i}"
                    if st.button("🗑", key=delete_key, disabled=disable_status):
                        delete_history_item(st.session_state.session_id, item['query'])
                        # Remove from session state history too
                        st.session_state.query_history.remove(item)
                        st.rerun()
        else:
            st.write("No previous queries")#↻ Dequeue

    
    col1, col2 = st.columns([9, 1])
    with col1:
        st.title("Welcome to Fiftytwo AI Help & Knowledge Center")
    with col2:
        st.write("")
        st.write("")
        st.write("")        
        st.image("logo.png", width=100, output_format="auto")
    collection = build_collection()
    
    with st.form("query_form", clear_on_submit=False):
        query = st.text_area(
            "Enter your query",
            label_visibility="collapsed",
            help="Search for Fiftytwo's products and services",
            placeholder="Ask something about fiftytwo...",

        )

        if st.session_state.is_processing:
            button_text = "🟥" 
            button_type = "secondary"
            button_help = "Cancel/Dequeue"

        else:
            button_text = " ➥ "
            button_type = "primary"
            button_help = "Submit your query"
        
        submit_button = st.form_submit_button(label = button_text, type=button_type, help=button_help)

    status_container = st.empty()

    col_history, col_retry = st.columns([1, 3])
    # History toggle button for considering response history
    with col_history:
        # Check if history exists in the database and in session state
        history_exists = False
        try:
            history = retrieve_history_context(st.session_state.session_id)
            history_exists = len(history) > 0
            # Update the session state to reflect if history exists
            st.session_state.history_exist = history_exists
        except:
            history_exists = False
            st.session_state.history_exist = False
        
        # Also check if query_history in session state is not empty
        session_history_exists = len(st.session_state.query_history) > 0
        
        # If no history exists anywhere, automatically turn off the history toggle
        if not history_exists and not session_history_exists:

            st.session_state.history_enabled = False
        
        # Set toggle status - disable if processing or no history exists (both in DB and session)
        toggle_status = st.session_state.is_processing or (not history_exists and not session_history_exists)
        
        # Update the toggle to use and update session state
        st.session_state.history_enabled = st.toggle("Enable History", 
                                                   value=st.session_state.history_enabled, 
                                                   disabled=toggle_status)
        history_context = ""
        if st.session_state.history_enabled:
            try:
                
                history = retrieve_history_context(st.session_state.session_id)
                
                if (not history or len(history) == 0) and len(st.session_state.query_history) > 0:
                    history = [(item["query"], item["response"]) for item in st.session_state.query_history]
                
                if history and len(history) > 0:
                    history_context = "\n".join([f"query: {item[0]}\nResponse: {item[1]}" for item in history])
                else:
                    st.warning("No history available")
                    
            except Exception as e:
                st.warning(f"Error retrieving history: {str(e)}")
                # Fallback to session state history
                if len(st.session_state.query_history) > 0:
                    history = [(item["query"], item["response"]) for item in st.session_state.query_history]
                    history_context = "\n".join([f"query: {item[0]}\nResponse: {item[1]}" for item in history])
    with col_retry:
        toggle_status = False
        has_history = st.session_state.history_exist or len(st.session_state.query_history) > 0
        if st.session_state.is_processing or not has_history:
            toggle_status = True                
        if st.session_state.done:
            retry_button = st.button("↻ Retry", disabled=toggle_status, type="tertiary")
            if retry_button:
                
                if st.session_state.top_k <= 8:
                    st.session_state.top_k += 2
                elif st.session_state.top_k == 0 or st.session_state.top_k < 0:
                    st.session_state.top_k = 5
                elif st.session_state.top_k >= 9:
                    st.session_state.top_k += 1
                elif st.session_state.top_k >= 15:
                    st.session_state.top_k -= 1
                else:
                    st.session_state.top_k = 5
                
                # Directly trigger the query submission if we have a previous query
                if st.session_state.current_response["query"]:
                    query = st.session_state.current_response["query"]
                    reset_state()
                    st.session_state.last_activity = time()
                    st.session_state.is_processing = True
                    success = qm.enqueue_query(st.session_state.session_id)
                    if not success:
                        status_container.warning("Your query is already in the queue.")
                    st.rerun()

    if st.session_state.current_response["response"] and not st.session_state.is_processing:
        st.markdown("##### Response")
        st.markdown(st.session_state.current_response["response"], unsafe_allow_html=True)
        if st.session_state.current_response["sources"]:
            st.markdown("##### Sources:")
            for url in st.session_state.current_response["sources"]:
                st.markdown(f"- {url}")
            st.markdown(f"###### Time: **{st.session_state.current_response['time']}**")

    if submit_button:
        st.session_state.top_k = 5
        if st.session_state.is_processing:
            request_stop()
            if not qm.is_my_turn(st.session_state.session_id):
                qm.dequeue_query(st.session_state.session_id)
                status_container.empty()
            else:
                # If we have a partial response, save it
                if 'partial_response' in st.session_state and st.session_state.partial_response:
                    st.session_state.current_response["response"] = st.session_state.partial_response
                    st.session_state.query_history.append({
                        "query": st.session_state.current_response["query"],
                        "response": st.session_state.partial_response,
                        "sources": st.session_state.current_response.get("sources", []),
                        "time": "stopped"
                    })
                release_and_dequeue()
                handle_stop_and_restart(status_container)
            reset_state()
            st.rerun()
        elif query:
            if qm.is_in_queue(st.session_state.session_id):
                status_container.warning("You already have a query in the queue. Please wait or cancel it.")
                st.session_state.is_processing = True
                st.rerun()
                return
            reset_state()
            st.session_state.last_activity = time()
            if len(query.split()) < 2 or is_repetitive_input(query):
                st.error("Please enter a valid question.")
                return
            st.session_state.is_processing = True
            success = qm.enqueue_query(st.session_state.session_id)
            if not success:
                status_container.warning("Your query is already in the queue.")
            st.rerun()

    if st.session_state.is_processing and not st.session_state.stop_requested:
        
        time_flag = False
        if st.session_state.is_processing and current_pos == 1:
            time_flag = True
        with st.spinner("Processing...", show_time = time_flag):
            last_queue_update = time()  # Set this only once at the beginning
            queue_start_time = time()   # Track when we entered the queue
            # In queue phase
            while not qm.is_my_turn(st.session_state.session_id):
                qm.clean_first_if_stale()
                if st.session_state.stop_requested:
                    qm.dequeue_query(st.session_state.session_id)
                    status_container.warning("Query cancelled.")
                    st.session_state.is_processing = False
                    st.rerun()
                    return
                qm.update_activity(st.session_state.session_id)
                lock_holder = qm.get_lock_holder()
                if current_pos == -1:
                    status_container.empty()
                    st.session_state.is_processing = False
                    st.rerun()
                    return
                current_time = time()
                if current_pos > 1:
                    elapsed_time = current_time - queue_start_time
                    initial_wait_time = current_pos * 90 + int(random() * 2) + 1
                    remaining_wait_time = max(initial_wait_time - elapsed_time, 0)
                    
                    minutes = int(remaining_wait_time // 60)
                    seconds = int(remaining_wait_time % 60)
                    
                    if seconds > 0 or minutes > 0:
                        status_container.info(f"Your query is in queue position {current_pos}. Approx. waiting period: {minutes}m {seconds}s.")
                    else:
                        status_container.info(f"Your query is in queue position {current_pos}. Processing soon...")
                else:
                    status_container.info("Processing your request...")
                
                if current_time - last_queue_update > 1:
                    last_queue_update = current_time
                    if current_pos == 1 and not lock_holder:
                        qm.process_next_in_queue()
                sleep(1)

            # Now we're processing
            status_container.info("Processing your request...")
            # Rest of processing logic
            if not qm.try_lock(st.session_state.session_id):
                status_container.warning("Server is busy. Re-submit your query shortly...")
                qm.dequeue_query(st.session_state.session_id)
                st.session_state.is_processing = False
                st.rerun()
                return

            qm.ensure_ollama_running()
            try:
                def check_stop():
                    if st.session_state.stop_requested:
                        return True
                    qm.update_activity(st.session_state.session_id)
                    return False

                query_embedding = embed_text(query, check_stop=check_stop)
                if query_embedding is None or st.session_state.stop_requested:
                    handle_stop_and_restart(status_container)
                    return

                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=st.session_state.top_k,
                    include=["documents", "metadatas"]
                )
                qm.update_activity(st.session_state.session_id)
                if st.session_state.stop_requested:
                    handle_stop_and_restart(status_container)
                    return

                if not results['documents'] or not results['documents'][0]:
                    status_container.warning("No relevant documents found for your query.")
                    release_and_dequeue()
                    st.session_state.is_processing = False
                    return

                context = "\n".join([doc for sublist in results['documents'] for doc in sublist])

                # Add debug print before prompt construction
                #st.write(f"Before prompt - History enabled: {st.session_state.history_enabled}, History context exists: {bool(history_context)}")

                if st.session_state.history_enabled and history_context:
                    prompt = (
                        f"You are an AI overview generator based on the following contexts and response history/previous responses given in markdown format: --beginning of contexts-- '{context}'--end of contexts--, "
                        f"here is your previous responses and their respective queries --beginning of response history -- {history_context} --end of response history--"
                        "based on your own knowledge and previous response/response history. Moreover, you should not mention anything like The provided "
                        "text does not mention. You should start responding without putting any introduction or conclusion. You only mention what is mentioned in the contexts and response history."
                        f"Now answer the following question: "
                        f"{query}"
                    )
                    
                    
                else:
                    prompt = (
                        f"You are an AI overview generator based on the following contexts given in markdown format: --beginning of contexts-- '{context}'--end of contexts--, "
                        "based on your own knowledge. Moreover, you should not mention anything like The provided "
                        "text does not mention. You should start responding without putting any introduction or conclusion."
                        "You only mention what is mentioned in the contexts and response history."
                        f"Now answer the following question: "
                        f"{query}"                        
                    )
                    
                    

                #st.write(prompt)
                print(prompt)

                response_placeholder = st.empty()
                full_response = ""
                status_container.info("Processing your request...")

                start_time = time()
                if st.session_state.stop_requested:
                    handle_stop_and_restart(status_container)
                    return

                response_stream = ollama.generate(model="llama3.2", prompt=prompt, stream=True)
                chunk_counter = 0
                st.session_state.partial_response = ""  # Initialize partial response

                for chunk in response_stream:
                    if st.session_state.stop_requested:
                        # Save the partial response before stopping
                        st.session_state.partial_response = full_response
                        handle_stop_and_restart(status_container)
                        break
                    chunk_counter += 1
                    if chunk_counter % 2 == 0:
                        qm.update_activity(st.session_state.session_id)
                    if "response" in chunk:
                        chunk_text = chunk["response"]
                        full_response += chunk_text
                        st.session_state.partial_response = full_response  # Update partial response
                        response_placeholder.markdown(full_response, unsafe_allow_html=True)

                if not st.session_state.stop_requested and full_response:
                    status_container.empty()
                    unique_urls = set()
                    for meta in [meta for sublist in results['metadatas'] for meta in sublist]:
                        unique_urls.add(meta['url'])
                    sources_list = list(unique_urls)
                    elapsed_time = time() - start_time
                    minutes = int(elapsed_time // 60)
                    seconds = int(elapsed_time % 60)
                    time_str = f"{minutes}m {seconds}s"
                    st.session_state.current_response = {
                        "query": query,
                        "response": full_response,
                        "sources": sources_list,
                        "time": time_str
                    }
                    st.session_state.query_history.append({
                        "query": query,
                        "response": full_response,
                        "sources": sources_list,
                        "time": time_str
                    })
                    st.session_state.history_exist = True
                    st.session_state.is_processing = False
                    response_history_database(session_id=st.session_state.session_id, query=query, full_response=full_response)
                    st.rerun()

            except Exception as e:
                if st.session_state.stop_requested:
                    handle_stop_and_restart(status_container)
                else:
                    status_container.error(f"An error occurred: {str(e)}")
                release_and_dequeue()
                st.session_state.is_processing = False
                st.rerun()
                return
            finally:
                release_and_dequeue()
                if st.session_state.stop_requested:
                    handle_stop_and_restart(status_container)
                    if qm.get_queue_length() > 0:
                        qm.process_next_in_queue()
                    st.session_state.stop_requested = False
                    st.rerun()
                else:
                    st.session_state.is_processing = False
                    if qm.get_queue_length() > 0:
                        qm.process_next_in_queue()

    st.session_state.done = True            

if __name__ == "__main__":
    main()
