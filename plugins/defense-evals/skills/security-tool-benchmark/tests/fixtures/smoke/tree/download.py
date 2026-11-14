import os


def download(name):
    # serves a file by name
    path = os.path.join('/srv/files', name)
    return open(path).read()
