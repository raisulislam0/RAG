## Running the Project with Docker

This project is fully containerized for easy local development and deployment. The setup uses **Python 3.11-slim** for the application and the latest official **Redis** image for queue management. All Python dependencies are installed in a virtual environment as specified in `requirements.txt`.

### Quick Start

1. **Build and launch the services:**

   ```bash
   docker compose up --build
   ```

   This command builds the application image and starts both the Streamlit app and Redis services.

2. **Access the AI Help Center:**

   - Open your browser to [http://localhost:8501](http://localhost:8501) to use the Streamlit UI.

### Service Overview

- **Streamlit App** (`python-streamlit`)
  - Runs on **Python 3.11-slim**
  - Exposes port **8501** (host → container)
  - Installs dependencies from `requirements.txt` in a virtual environment
  - Runs as a non-root user for security
  - Depends on Redis for queue management

- **Redis**
  - Uses the latest official image
  - Data is persisted in the `redis-data` Docker volume
  - Healthcheck is enabled for reliability

### Configuration

- **Environment Variables:**
  - No required environment variables by default. If you need to set any, create a `.env` file and uncomment the `env_file` line in `compose.yaml`.

- **Networks and Volumes:**
  - Both services are connected via the `appnet` Docker network
  - Redis data is stored in the `redis-data` volume for persistence

### Ports

- **8501:** Streamlit UI (host → container)

---

For advanced configuration or troubleshooting, refer to the `Dockerfile` and `compose.yaml` in the project root.
