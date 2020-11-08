import xml
import json
import yaml
from munch import Munch
from collections import deque, namedtuple

def main():
    b = Munch(foo=Munch(lol=True), hello=42, ponies='red')
    json_b = json.dumps(b)
    q = deque(['a','c','b'])
    q.append('d')
    print(q)
    point = namedtuple('Point',['x','y'])
    p = point(1,2)
    print(p)
    print(b)

    print(json_b)

if __name__ == '__main__':
    main()