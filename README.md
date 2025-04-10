# Fiftytwo AI Help Center

This project is a **Streamlit-based AI Help Center** for **Fiftytwo**, a retail solutions provider. The system:

- Crawls Fiftytwo's help documentation website using a **sitemap generator**
- Cleans and processes the **HTML content into text**
- Embeds the text chunks using **Ollama's embedding model**
- Stores these embeddings in a **ChromaDB vector database**
- Provides a **user interface** where users can ask questions
- Implements a **queue system with Redis** to manage concurrent requests
- Retrieves relevant documentation based on **semantic search**
- Generates responses using the **Llama3.2 model via Ollama**
- Displays the response with **source citations**

The application includes:

- **Input validation**
- **Queue management**
- A **streaming response interface** to create a responsive knowledge base for Fiftytwo's products and services
