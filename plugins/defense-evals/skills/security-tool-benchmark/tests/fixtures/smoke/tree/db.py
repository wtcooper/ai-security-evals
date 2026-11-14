def find_user(cur, name):
    cur.execute("SELECT * FROM users WHERE name = '" + name + "'")
    return cur.fetchone()
