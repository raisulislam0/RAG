import redis
import time
import psutil
import subprocess
import os
import time

# Redis connection
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

QUEUE_KEY = "query_queue"
LOCK_KEY = "query_lock"
LOCK_EXPIRY = 60  # seconds - increased to allow for longer operations
ACTIVITY_TIMEOUT = 180  # 5 minutes - session considered stale after this
OLLAMA_IDLE_THRESHOLD = 5.0  # CPU usage percentage below which Ollama is considered idle
OLLAMA_AUTO_SHUTDOWN_SECONDS = 10  # Shutdown Ollama after this many seconds of idle time

# Track when Ollama was last active
LAST_OLLAMA_ACTIVITY_KEY = "last_ollama_activity"

def is_in_queue(session_id):
    """Check if a session is already in the queue"""
    return r.sismember("active_sessions", session_id)

def enqueue_query(session_id):
    # Check if not already in queue
    if not is_in_queue(session_id):
        # First, clean stale sessions before adding new one
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
    # Get the first session in queue (if any)
    next_session = get_next_in_queue()

    if next_session:
        # We could set a notification flag for that session
        # This would be useful if we had a way to communicate between sessions
        # For now, we'll just ensure the lock is released so the next session can proceed
        r.delete(LOCK_KEY)

        # Set a flag that this session should check if it's their turn
        r.set(f"notify_{next_session}", "1", ex=30)  # Expires in 30 seconds
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
    # If the session holds the lock, it’s not stale
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
        # If no activity recorded, assume just started
        update_ollama_activity()
        return 0

    return time.time() - float(last_activity)

def is_ollama_idle():
    """Check if Ollama process is idle (low CPU usage)"""
    try:
        # First get a list of all Ollama processes
        ollama_processes = []
        for proc in psutil.process_iter(['pid', 'name']):
            if 'ollama' in proc.info['name'].lower():
                ollama_processes.append(proc)

        # If no Ollama processes found, consider it idle
        if not ollama_processes:
            return True

        # Get initial CPU measurements
        for proc in ollama_processes:
            proc.cpu_percent(interval=None)  # First call just initializes the measurement

        # Wait a moment for accurate measurement
        time.sleep(0.5)

        # Check CPU usage of all Ollama processes
        total_cpu = 0
        for proc in ollama_processes:
            try:
                cpu = proc.cpu_percent(interval=None)
                total_cpu += cpu
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Process might have terminated
                continue

        # If CPU usage is above threshold, update activity timestamp
        if total_cpu >= OLLAMA_IDLE_THRESHOLD:
            update_ollama_activity()

        # If total CPU usage is below threshold, consider it idle
        return total_cpu < OLLAMA_IDLE_THRESHOLD
    except Exception as e:
        print(f"Error checking Ollama process: {e}")
        # Default to not idle if there's an error
        return False

def should_shutdown_ollama():
    """Check if Ollama should be shut down due to inactivity"""
    # If there are queries in the queue, don't shut down
    if get_queue_length() > 0 or get_lock_holder():
        return False

    # Check if Ollama is idle
    if not is_ollama_idle():
        return False

    # Check how long it's been idle
    idle_time = get_ollama_idle_time()
    return idle_time > OLLAMA_AUTO_SHUTDOWN_SECONDS

def shutdown_ollama():
    """Shut down Ollama to save resources"""
    try:
        # First, try to find and terminate all Ollama processes
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
    # Check if Ollama is already running
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
        # Use subprocess.Popen to start the process without waiting for it to complete
        # On Windows, we need to use the full path or rely on the PATH environment variable
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

        # Give it a moment to start up
        time.sleep(2)

        # Update activity timestamp
        update_ollama_activity()
        return success
    except Exception:
        return False

def restart_ollama(force=False):
    """Restart the Ollama process to free up resources

    Args:
        force: If True, restart even if there are active queries
    """
    try:
        # Check if there are any active queries in the queue
        queue_length = get_queue_length()
        lock_holder = get_lock_holder()

        if not force and (queue_length > 0 or lock_holder):
            return False

        # First, try to find and terminate all Ollama processes
        ollama_procs = []
        for proc in psutil.process_iter(['pid', 'name']):
            if 'ollama' in proc.info['name'].lower():
                ollama_procs.append(proc)

        if ollama_procs:
            print(f"Found {len(ollama_procs)} Ollama processes to terminate")
            for proc in ollama_procs:
                try:
                    print(f"Terminating Ollama process with PID {proc.pid}")
                    proc.terminate()
                except Exception as e:
                    print(f"Error terminating process {proc.pid}: {e}")

            # Wait for processes to terminate (max 5 seconds)
            time.sleep(1)  # Give a moment for processes to start terminating

            # Check if any processes are still running and force kill them
            for proc in ollama_procs:
                try:
                    if proc.is_running():
                        print(f"Process {proc.pid} still running, force killing...")
                        proc.kill()
                except Exception as e:
                    print(f"Error killing process {proc.pid}: {e}")
        else:
            print("No Ollama processes found to terminate")

        # Make sure all Ollama processes are gone
        time.sleep(1)
        remaining = [p for p in psutil.process_iter(['pid', 'name']) if 'ollama' in p.info['name'].lower()]
        if remaining:
            print(f"Warning: {len(remaining)} Ollama processes still running after termination attempts")

        # Start Ollama again
        print("Starting Ollama process...")
        # Use subprocess.Popen to start the process without waiting for it to complete
        # On Windows, we need to use the full path or rely on the PATH environment variable
        success = False

        # Method 1: Try with just the command (relies on PATH)
        try:
            subprocess.Popen("ollama serve",
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            creationflags=subprocess.CREATE_NO_WINDOW)
            success = True
            print("Started Ollama using PATH")
        except Exception as e:
            print(f"Error starting Ollama with simple command: {e}")

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
                    print(f"Started Ollama from {ollama_path}")
                else:
                    print(f"Ollama not found at {ollama_path}")
            except Exception as e2:
                print(f"Error starting Ollama with full path: {e2}")

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
                print("Started Ollama using PowerShell")
            except Exception as e3:
                print(f"Error starting Ollama with PowerShell: {e3}")

        # Give it a moment to start up
        time.sleep(3)

        # Verify Ollama is running
        ollama_running = False
        for _ in range(3):  # Try checking a few times
            if any('ollama' in p.info['name'].lower() for p in psutil.process_iter(['pid', 'name'])):
                ollama_running = True
                break
            time.sleep(1)

        if ollama_running:
            print("Verified Ollama is running after restart")
        else:
            print("Warning: Could not verify Ollama is running after restart attempts")

        return success
    except Exception as e:
        print(f"Error restarting Ollama: {e}")
        return False

def clean_stale_sessions():
    """Remove stale sessions from queue and release their locks"""
    # Get all sessions in queue
    queue = r.lrange(QUEUE_KEY, 0, -1)
    stale_found = False

    for session_id in queue:
        if is_session_stale(session_id):
            # Remove from queue and active sessions
            dequeue_query(session_id)
            # Release lock if held
            release_lock(session_id)
            # Clean up any notification flags
            r.delete(f"notify_{session_id}")
            r.delete(f"activity_{session_id}")
            stale_found = True

    # Check if lock is held by a stale session
    lock_holder = r.get(LOCK_KEY)
    if lock_holder and is_session_stale(lock_holder):
        # Force release the lock
        r.delete(LOCK_KEY)
        stale_found = True

    # If we found and removed stale sessions, and Ollama is idle,
    # process the next query in the queue
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
        time.sleep(1)  # Wait to allow graceful termination
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
    first = r.lindex(QUEUE_KEY, 0)  # Get the first session ID in the queue
    if first and is_session_stale(first):
        # Remove from queue and active sessions set
        r.lrem(QUEUE_KEY, 0, first)
        r.srem("active_sessions", first)
        # Clean up the activity timestamp key
        r.delete(f"activity_{first}")
        return True  # Indicate a stale session was removed
    return False  # No stale session found     
       
    