import streamlit as st
import ollama
import time
import uuid

from processor import input_validation, is_repetitive_input, embed_text, build_collection
import queue_manager as qm

st.set_page_config(
    page_title="Fiftytwo AI Help",
    layout="centered"
)

if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if 'stop_requested' not in st.session_state:
    st.session_state.stop_requested = False

if 'is_processing' not in st.session_state:
    st.session_state.is_processing = False

if 'last_activity' not in st.session_state:
    st.session_state.last_activity = time.time()

if 'last_queue_check' not in st.session_state:
    st.session_state.last_queue_check = time.time()

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
    """Handle stopping processing and shutting down Ollama if queue is empty.

    Args:
        status_container: Streamlit container for status messages
        force_restart: If True, force restart Ollama even if there are active queries
    """
    reset_state()

    queue_length = qm.get_queue_length()
    lock_holder = qm.get_lock_holder()
    other_active_queries = (queue_length > 0 and qm.get_queue_position(st.session_state.session_id) == -1) or \
                           (lock_holder and lock_holder != st.session_state.session_id)

    if not other_active_queries or force_restart:
        qm.shutdown_ollama()
        status_container.empty()
    else:
        status_container.empty()

def check_stale_sessions():
    """Check for and clean up stale sessions"""
    current_time = time.time()

    if current_time - st.session_state.last_activity > 3:  
        if 'session_id' in st.session_state:
            qm.dequeue_query(st.session_state.session_id)
            qm.release_lock(st.session_state.session_id)
        reset_state()
        st.session_state.last_activity = current_time

    st.session_state.last_activity = current_time
    qm.clean_stale_sessions()

def ensure_ollama_fresh_start():
    """Ensure Ollama is running when needed and shuts down when idle"""
    queue_length = qm.get_queue_length()
    lock_holder = qm.get_lock_holder()

    if queue_length > 0 or lock_holder:
        qm.ensure_ollama_running()
    elif qm.should_shutdown_ollama():  
        qm.shutdown_ollama()

def main():
    ensure_ollama_fresh_start()
    check_stale_sessions()

    current_time = time.time()
    if current_time - st.session_state.last_queue_check > 10:
        st.session_state.last_queue_check = current_time
        qm.clean_stale_sessions()
        qm.process_next_in_queue()

    st.title("Welcome to Fiftytwo AI Help & Knowledge Center")

    collection = build_collection()

    with st.form("query_form", clear_on_submit=False):
        query = st.text_area(
            "Enter your question",
            label_visibility="visible",
            help="Search for Fiftytwo's products and services"
        )
        button_text = "🟩" if st.session_state.is_processing else "↩"
        button_type = "secondary" if st.session_state.is_processing else "primary"

        if button_text == "🟩":
            button_help = "Cancel"
        else:
            button_help = "Submit"

        submit_button = st.form_submit_button(button_text, type=button_type, help=button_help)

    status_container = st.empty()

    if submit_button:
        if st.session_state.is_processing:
            request_stop()
            if not qm.is_my_turn(st.session_state.session_id):
                qm.dequeue_query(st.session_state.session_id)
                status_container.empty()
            else:
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
            st.session_state.last_activity = time.time()

            if len(query.split()) < 2 or input_validation(query) or is_repetitive_input(query):
                st.error("Please enter a valid question.")
                return

            st.session_state.is_processing = True
            success = qm.enqueue_query(st.session_state.session_id)
            if not success:
                status_container.warning("Your query is already in the queue.")
            st.rerun()

    if st.session_state.is_processing and not st.session_state.stop_requested:
        with st.spinner("Processing..."):
            last_queue_update = 0
            while not qm.is_my_turn(st.session_state.session_id):
                qm.clean_first_if_stale()
                
                if st.session_state.stop_requested:
                  
                    qm.dequeue_query(st.session_state.session_id)
                    status_container.warning("Query cancelled.")
                    st.session_state.is_processing = False
                    st.rerun()
                    return

            
                qm.update_activity(st.session_state.session_id)

                # Update position dynamically
                current_pos = qm.get_queue_position(st.session_state.session_id)
                lock_holder = qm.get_lock_holder()

                # If position is -1, we've been removed from queue
                if current_pos == -1:
                    status_container.empty()
                    st.session_state.is_processing = False
                    st.rerun()
                    return

              
                if current_pos > 1:
                    status_container.info(f"Your request is in queue. Position: {current_pos}")
                else:
                    status_container.info("Processing your request...")


                current_time = time.time()
                if current_time - last_queue_update > 1:
                    last_queue_update = current_time
                    if current_pos == 1 and not lock_holder:
                        qm.process_next_in_queue()

                time.sleep(1)

            status_container.info("Processing your request...")
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
                    n_results=3,
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
                prompt = (
                    f"You are an AI overview generator based on the following contexts given in markdown format: --beginning of contexts-- '{context}'--end of contexts--, "
                    f"mention everything you know about the {query} only if it is mentioned in the contexts. DON'T assume anything "
                    "based on your own knowledge. Moreover, you should not mention anything like The provided "
                    "text does not mention. You should start responding without putting any introduction or conclusion."
                )

                st.write(prompt)

                heading_placeholder = st.empty()
                response_placeholder = st.empty()
                full_response = ""
                status_container.info("Processing your request...")

                start_time = time.time()
                if st.session_state.stop_requested:
                    handle_stop_and_restart(status_container)
                    return

                response_stream = ollama.generate(model="llama3.2", prompt=prompt, stream=True)
                chunk_counter = 0
                for chunk in response_stream:
                    if st.session_state.stop_requested:
                        handle_stop_and_restart(status_container)
                        break

                    chunk_counter += 1
                    if chunk_counter % 2 == 0:
                        qm.update_activity(st.session_state.session_id)

                    if "response" in chunk:
                        chunk_text = chunk["response"]
                        if not full_response:
                            heading_placeholder.markdown("##### Response")
                        full_response += chunk_text
                        response_placeholder.markdown(full_response, unsafe_allow_html=True)

                if not st.session_state.stop_requested and full_response:
                    status_container.empty()
                    st.markdown("##### Sources:")
                    unique_urls = set()
                    for meta in [meta for sublist in results['metadatas'] for meta in sublist]:
                        unique_urls.add(meta['url'])
                    for url in unique_urls:
                        st.markdown(f"- {url}")
                    elapsed_time = time.time() - start_time
                    minutes = int(elapsed_time // 60)
                    seconds = int(elapsed_time % 60)
                    st.info(f"Response time: {minutes}m {seconds}s")

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

    qm.shutdown_ollama_if_queue_empty()
                        

if __name__ == "__main__":
    main()