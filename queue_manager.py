import redis
import time
import psutil
import subprocess
import os
import time

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

QUEUE_KEY = "query_queue"
LOCK_KEY = "query_lock"
LOCK_EXPIRY = 5  
ACTIVITY_TIMEOUT = 120  
OLLAMA_IDLE_THRESHOLD = 60  
OLLAMA_AUTO_SHUTDOWN_SECONDS = 1 

# Track when Ollama was last active
LAST_OLLAMA_ACTIVITY_KEY = "last_ollama_activity"

def is_in_queue(session_id):
    """Check if a session is already in the queue"""
    return r.sismember("active_sessions", session_id)

def enqueue_query(session_id):
    if not is_in_queue(session_id):
        clean_stale_sessions()

        # Add to queue and active sessions
        r.rpush(QUEUE_KEY, session_id)
        r.sadd("active_sessions", session_id)

        # Set activity timestamp
        r.set(f"activity_{session_id}", str(time.time()), ex=ACTIVITY_TIMEOUT)

        # Set expiry on session
        r.expire(session_id, ACTIVITY_TIMEOUT)

        return True  # Successfully added to queue
    return False  # Already in queue

def get_queue_position(session_id):
    queue = r.lrange(QUEUE_KEY, 0, -1)
    try:
        return queue.index(session_id) + 1
    except ValueError:
        return -1

def is_my_turn(session_id):
    first = r.lindex(QUEUE_KEY, 0)
    return first == session_id

def try_lock(session_id):
    return r.set(LOCK_KEY, session_id, nx=True, ex=LOCK_EXPIRY)

def get_lock_holder():
    """Get the session ID that currently holds the lock, or None if no lock"""
    return r.get(LOCK_KEY)

def release_lock(session_id):
    if r.get(LOCK_KEY) == session_id:
        r.delete(LOCK_KEY)

def dequeue_query(session_id):
    r.lrem(QUEUE_KEY, 0, session_id)
    r.srem("active_sessions", session_id)

def get_queue_length():
    """Return the current length of the queue"""
    return r.llen(QUEUE_KEY)

def get_next_in_queue():
    """Get the next session ID in the queue without removing it"""
    return r.lindex(QUEUE_KEY, 0)

def process_next_in_queue():
    """
    Check if there's another session in queue and notify it to process
    This is mainly used for UI updates across sessions
    """
    next_session = get_next_in_queue()

    if next_session:
        r.delete(LOCK_KEY)
        r.set(f"notify_{next_session}", "1", ex=1)  
        return True
    return False

def should_check_queue(session_id):
    """Check if this session has been notified to check the queue"""
    flag = r.get(f"notify_{session_id}")
    if flag:
        r.delete(f"notify_{session_id}")
        return True
    return False

def update_activity(session_id):
    """Update the last activity timestamp for a session"""
    r.set(f"activity_{session_id}", str(time.time()), ex=ACTIVITY_TIMEOUT)

def is_session_stale(session_id):
    if r.get(LOCK_KEY) == session_id:
        return False
    timestamp = r.get(f"activity_{session_id}")
    if not timestamp:
        return True
    last_activity = float(timestamp)
    return (time.time() - last_activity) > ACTIVITY_TIMEOUT


def update_ollama_activity():
    """Update the timestamp of when Ollama was last active"""
    r.set(LAST_OLLAMA_ACTIVITY_KEY, str(time.time()))

def get_ollama_idle_time():
    """Get how many seconds Ollama has been idle"""
    last_activity = r.get(LAST_OLLAMA_ACTIVITY_KEY)
    if not last_activity:
        update_ollama_activity()
        return 0

    return time.time() - float(last_activity)

def is_ollama_idle():
    """Check if Ollama process is idle (low CPU usage)"""
    try:
        
        ollama_processes = []
        for proc in psutil.process_iter(['pid', 'name']):
            if 'ollama' in proc.info['name'].lower():
                ollama_processes.append(proc)

        if not ollama_processes:
            return True

        for proc in ollama_processes:
            proc.cpu_percent(interval=None)  

        time.sleep(0.5)

        
        total_cpu = 0
        for proc in ollama_processes:
            try:
                cpu = proc.cpu_percent(interval=None)
                total_cpu += cpu
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if total_cpu >= OLLAMA_IDLE_THRESHOLD:
            update_ollama_activity()

        return total_cpu < OLLAMA_IDLE_THRESHOLD
    except Exception as e:
        print(f"Error checking Ollama process: {e}")
        return False

def should_shutdown_ollama():
    """Check if Ollama should be shut down due to inactivity"""
    if get_queue_length() > 0 or get_lock_holder():
        return False

    if not is_ollama_idle():
        return False

    idle_time = get_ollama_idle_time()
    return idle_time > OLLAMA_AUTO_SHUTDOWN_SECONDS

def shutdown_ollama():
    """Shut down Ollama to save resources"""
    try:
        ollama_procs = []
        for proc in psutil.process_iter(['pid', 'name']):
            if 'ollama' in proc.info['name'].lower():
                ollama_procs.append(proc)

        if ollama_procs:
            for proc in ollama_procs:
                try:
                    proc.terminate()
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            return True
        return False
    except Exception:
        return False

def get_ollama_process():
    """Get the Ollama process if it's running"""
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            if 'ollama' in proc.info['name'].lower():
                return proc
        return None
    except Exception as e:
        print(f"Error getting Ollama process: {e}")
        return None

def ensure_ollama_running():
    """Make sure Ollama is running"""
    ollama_running = False
    for proc in psutil.process_iter(['pid', 'name']):
        if 'ollama' in proc.info['name'].lower():
            ollama_running = True
            break

    if ollama_running:
        # Update activity timestamp
        update_ollama_activity()
        return True

    # Start Ollama
    return start_ollama()

def start_ollama():
    """Start the Ollama process"""
    try:
        success = False

        # Method 1: Try with just the command (relies on PATH)
        try:
            subprocess.Popen("ollama serve",
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW)
            success = True
        except Exception:
            pass

        # Method 2: Try with potential default installation path
        if not success:
            try:
                ollama_path = os.path.expanduser("~\\AppData\\Local\\ollama\\ollama.exe")
                if os.path.exists(ollama_path):
                    subprocess.Popen(f'"{ollama_path}" serve',
                                    shell=True,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
                    success = True
            except Exception:
                pass

        # Method 3: Try with Start-Process PowerShell command
        if not success:
            try:
                ps_command = "Start-Process -WindowStyle Hidden -FilePath 'ollama' -ArgumentList 'serve'"
                subprocess.Popen(["powershell", "-Command", ps_command],
                                shell=True,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                creationflags=subprocess.CREATE_NO_WINDOW)
                success = True
            except Exception:
                pass
        time.sleep(2)

        # Update activity timestamp
        update_ollama_activity()
        return success
    except Exception:
        return False


def clean_stale_sessions():
    """Remove stale sessions from queue and release their locks"""
    # Get all sessions in queue
    queue = r.lrange(QUEUE_KEY, 0, -1)
    stale_found = False

    for session_id in queue:
        if is_session_stale(session_id):
            dequeue_query(session_id)
            release_lock(session_id)
            r.delete(f"notify_{session_id}")
            r.delete(f"activity_{session_id}")
            stale_found = True

    lock_holder = r.get(LOCK_KEY)
    if lock_holder and is_session_stale(lock_holder):
        r.delete(LOCK_KEY)
        stale_found = True

    if stale_found and is_ollama_idle() and get_queue_length() > 0:
        process_next_in_queue()
def shutdown_ollama():
    """Shut down Ollama and its child processes to save resources"""
    try:
        ollama_procs = [p for p in psutil.process_iter(['pid', 'name']) if 'ollama' in p.info['name'].lower()]
        for proc in ollama_procs:
            # Terminate the process and its children
            for child in proc.children(recursive=True):
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            try:
                proc.terminate()
            except psutil.NoSuchProcess:
                pass
        time.sleep(1)  
        for proc in ollama_procs:
            if proc.is_running():
                for child in proc.children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                try:
                    proc.kill()
                except psutil.NoSuchProcess:
                    pass
        return True
    except Exception as e:
        print(f"Error shutting down Ollama: {e}")
        return False    

def clean_first_if_stale():
    """Remove the first session from the queue if it is stale."""
    first = r.lindex(QUEUE_KEY, 0)  
    if first and is_session_stale(first):
        r.lrem(QUEUE_KEY, 0, first)
        r.srem("active_sessions", first)
        r.delete(f"activity_{first}")
        return True  
    return False

def shutdown_ollama_if_queue_empty():
    """Shut down Ollama if the query queue is empty"""
    if get_queue_length() == 0 and not get_lock_holder():
        return shutdown_ollama()
    return False
    
