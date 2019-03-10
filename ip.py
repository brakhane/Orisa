from orisa.models import *

import logging

logging.basicConfig()
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
d = Database()
s = d.Session()

from orisa.tournament import *