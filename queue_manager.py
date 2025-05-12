import redis
import time
import psutil
import subprocess
import os
import signal

redis_host = os.environ.get('REDIS_HOST', 'localhost')
r = redis.Redis(host=redis_host, port=6379, db=0, decode_responses=True)

QUEUE_KEY = "query_queue"
LOCK_KEY = "query_lock"
LOCK_EXPIRY = 60  
ACTIVITY_TIMEOUT = 300  

LAST_OLLAMA_ACTIVITY_KEY = "last_ollama_activity"

def is_in_queue(session_id):
    """Check if a session is already in the queue"""
    return r.sismember("active_sessions", session_id)

def enqueue_query(session_id):
    if not is_in_queue(session_id):
        clean_stale_sessions()
        r.rpush(QUEUE_KEY, session_id)
        r.sadd("active_sessions", session_id)
        r.set(f"activity_{session_id}", str(time.time()), ex=ACTIVITY_TIMEOUT)
        r.expire(session_id, ACTIVITY_TIMEOUT)
        return True
    return False

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
    return r.get(LOCK_KEY)

def release_lock(session_id):
    if r.get(LOCK_KEY) == session_id:
        r.delete(LOCK_KEY)

def dequeue_query(session_id):
    r.lrem(QUEUE_KEY, 0, session_id)
    r.srem("active_sessions", session_id)

def get_queue_length():
    return r.llen(QUEUE_KEY)

def get_next_in_queue():
    return r.lindex(QUEUE_KEY, 0)

def process_next_in_queue():
    next_session = get_next_in_queue()
    if next_session:
        r.delete(LOCK_KEY)
        r.set(f"notify_{next_session}", "1", ex=1)
        return True
    return False

def should_check_queue(session_id):
    flag = r.get(f"notify_{session_id}")
    if flag:
        r.delete(f"notify_{session_id}")
        return True
    return False

def update_activity(session_id):
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
    r.set(LAST_OLLAMA_ACTIVITY_KEY, str(time.time()))

def get_ollama_idle_time():
    last_activity = r.get(LAST_OLLAMA_ACTIVITY_KEY)
    if not last_activity:
        update_ollama_activity()
        return 0
    return time.time() - float(last_activity)


def interrupt_ollama():
    """Send SIGINT to the Ollama process to gracefully interrupt processing"""
    try:
        import requests
        try:
            requests.post('http://localhost:11434/api/generate', 
                         json={'prompt': '', 'model': ''}, 
                         timeout=1)
            return True
        except Exception as e:
            print(f"Error canceling Ollama generation via API: {e}")
            
        ollama_procs = [p for p in psutil.process_iter(['pid', 'name']) if 'ollama' in p.info['name'].lower()]
        if ollama_procs:
            for proc in ollama_procs:
                try:
                    os.kill(proc.pid, signal.SIGINT)
                    print(f"Sent SIGINT to Ollama process {proc.pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as e:
                    print(f"Error sending SIGINT to Ollama process {proc.pid}: {e}")
            return True
        return False
    except Exception as e:
        print(f"Error interrupting Ollama: {e}")
        return False

def ensure_ollama_running():
    ollama_running = False
    for proc in psutil.process_iter(['pid', 'name']):
        if 'ollama' in proc.info['name'].lower():
            ollama_running = True
            break
    if ollama_running:
        update_ollama_activity()
        return True
    return start_ollama()

def start_ollama():
    try:
        success = False
        try:
            subprocess.Popen("ollama serve",
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW)
            success = True
        except Exception:
            pass
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
        update_ollama_activity()
        return success
    except Exception:
        return False

def clean_stale_sessions():
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
    if stale_found and get_queue_length() > 0:
        process_next_in_queue()

def clean_first_if_stale():
    first = r.lindex(QUEUE_KEY, 0)
    if first and is_session_stale(first):
        r.lrem(QUEUE_KEY, 0, first)
        r.srem("active_sessions", first)
        r.delete(f"activity_{first}")
        return True
    return False
