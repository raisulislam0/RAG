import streamlit as st
import hashlib
import ollama
import time
import uuid

from processor import is_gibberish, is_repetitive_input, embed_text, build_collection
import queue_manager as qm


# Page config
st.set_page_config(
    page_title="Fiftytwo AI Help",
    layout="centered"
)

# Initialize session ID for queue tracking
if 'session_id' not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

def get_cache_key(query, context):
    combined = (query + context).encode('utf-8')
    return hashlib.md5(combined).hexdigest()

def main():
    st.title("Welcome to Fiftytwo AI Help & Knowledge Center")

    # Initialize ChromaDB collection
    collection = build_collection()

    # Query input form
    with st.form("query_form"):
        query = st.text_input("Enter your question")
        submit_button = st.form_submit_button("Submit")

    if submit_button and query:
        if len(query.split()) < 2 or is_gibberish(query) or is_repetitive_input(query):
            st.error("Please enter a valid question.")
            return

        # Enqueue the session in Redis
        qm.enqueue_query(st.session_state.session_id)

        status_container = st.empty()  # Create a container for status messages

        with st.spinner("Processing..."):
            while not qm.is_my_turn(st.session_state.session_id):
                # Update position dynamically
                current_pos = qm.get_queue_position(st.session_state.session_id)
                status_container.info(f"Waiting your turn... Position in queue: {current_pos}")
                time.sleep(1)

            # Clear the waiting message and show processing message
            status_container.info("Processing your query...⏳")
            
            # Try to acquire Redis lock
            if not qm.try_lock(st.session_state.session_id):
                status_container.warning("Server is busy. Re-submit your query shortly...")
                return

            try:
                # Query embedding and document retrieval
                query_embedding = embed_text(query)
                results = collection.query(
                    query_embeddings=[query_embedding],
                    n_results=3,
                    include=["documents", "metadatas"]
                )

                if not results['documents'] or not results['documents'][0]:
                    status_container.warning("No relevant documents found for your query.")
                    return

                # Join context and prepare prompt
                context = "\n".join([doc for sublist in results['documents'] for doc in sublist])

                prompt = (
                    f"You are an AI overview generator based on the following information: '{context}', "
                    f"tell everything you know about the {query}; however, DON'T assume anything "
                    "based on your own knowledge. Moreover, you should not mention anything like The provided "
                    "text does not mention. You should start responding without putting any introduction or conclusion"
                )

                # Display the results
                st.markdown("### Response")
                response_placeholder = st.empty()
                full_response = ""

                # Update status to show generating response
                status_container.info("Generating response...⌛")

                start_time = time.time()
                response_stream = ollama.generate(model="llama3.2", prompt=prompt, stream=True)

                for chunk in response_stream:
                    if "response" in chunk:
                        chunk_text = chunk["response"]
                        full_response += chunk_text
                        response_placeholder.markdown(full_response, unsafe_allow_html=True)

                # Clear the status container after processing is complete
                status_container.empty()

                # Display sources
                st.markdown("### Sources")
                unique_urls = set()
                for meta in [meta for sublist in results['metadatas'] for meta in sublist]:
                    unique_urls.add(meta['url'])

                for url in unique_urls:
                    st.markdown(f"- {url}")

                elapsed_time = time.time() - start_time
                minutes = int(elapsed_time // 60)
                seconds = int(elapsed_time % 60)
                st.info(f"Response time: {minutes}m {seconds}s")
           

            finally:
                # Always release lock and dequeue
                qm.release_lock(st.session_state.session_id)         
                qm.dequeue_query(st.session_state.session_id)
        
    
if __name__ == "__main__":
    main()
