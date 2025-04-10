import redis

# Redis connection
r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

QUEUE_KEY = "query_queue"
LOCK_KEY = "query_lock"
LOCK_EXPIRY = 60  # seconds

def enqueue_query(session_id):
    if not r.sismember("active_sessions", session_id):
        r.rpush(QUEUE_KEY, session_id)
        r.sadd("active_sessions", session_id)
        r.expire(session_id, 300)  # 5 minutes

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

def release_lock(session_id):
    if r.get(LOCK_KEY) == session_id:
        r.delete(LOCK_KEY)

def dequeue_query(session_id):
    r.lrem(QUEUE_KEY, 0, session_id)
    r.srem("active_sessions", session_id)