import sqlite3
from db_utils import *
import scipy.stats as stats
import numpy as np
import math
from tqdm import tqdm
import ast

from runner import ALL_MUTS
from configs.projects import *
from configs.experiments import *

def as_seconds(milliseconds):
    return round(milliseconds / 1000, 2)

def as_percentage(p):
    return round(p * 100, 2)

samples = get_samples(S_KOMODO, [Z3_4_4_2, Z3_4_11_2, CVC5_1_0_3])

cfg = ExpConfig("test1", S_KOMODO, samples)

con = sqlite3.connect(DB_PATH)
cur = con.cursor()
unstable_table_name = "unstable_" + cfg.table_name

def build_unstable_table():
    cur.execute(f"""DROP TABLE IF EXISTS {unstable_table_name}""")

    cur.execute(f"""CREATE TABLE {unstable_table_name} (
        solver varchar(10),
        vanilla_path varchar(255),
        v_result_code varchar(10),
        v_elapsed_milli INTEGER,
        shuffle_summary varchar(100),
        rename_summary varchar(100),
        sseed_summary varchar(100)
        )""")

    for solver in cfg.samples:
        solver = str(solver)
        res = cur.execute(f"""
            SELECT query_path, result_code, elapsed_milli
            FROM {cfg.table_name}
            WHERE query_path = vanilla_path
            AND command LIKE ?
            """, (f"%{solver}%", ))

        vanilla_rows = res.fetchall()
        for (vanilla_path, v_rcode, v_time) in tqdm(vanilla_rows):
            # if v_rcode != 'unsat':
            #     print("???")
            #     print(vanilla_path)
            #     print(vanilla_path, v_rcode, v_time)
            
            res = cur.execute("DROP VIEW IF EXISTS query_view");
            res = cur.execute(f"""
                CREATE VIEW query_view AS
                SELECT result_code, elapsed_milli, perturbation FROM {cfg.table_name}
                WHERE query_path != vanilla_path
                AND command LIKE "%{solver}%" 
                AND vanilla_path = "{vanilla_path}" """)

            results = dict()

            for perturb in ALL_MUTS:
                res = cur.execute(f"""
                    SELECT * FROM query_view
                    WHERE perturbation = ?
                    """, (perturb,))
                rows = res.fetchall()
                sample_size = len(rows)
                veri_times = [r[1] for r in rows]
                veri_res = [1 if r[0] == 'unsat' else 0 for r in rows]
                if sample_size == 0:
                    print("[WARN] 0 sample size encountered")
                    continue
                p = sum(veri_res) / sample_size

                t_critical = stats.t.ppf(q=cfg.confidence_level, df=sample_size-1)  
                # get the sample standard deviation
                time_stdev = np.std(veri_times, ddof=1)
                results[perturb] = (as_percentage(p), as_seconds(time_stdev), sample_size)

            maybe = False
            for perturb, (p, _, _) in results.items():
                if p <= 0.9:
                    maybe = True
            if maybe:
                summaries = []
                for perturb, (p, std, sz) in results.items():
                    summary = [perturb, p, std, sz]
                    summaries.append(str(summary))

                cur.execute(f"""INSERT INTO {unstable_table_name}
                    VALUES(?, ?, ?, ?, ?, ?, ?);""", (solver, vanilla_path, v_rcode, v_time, summaries[0], summaries[1], summaries[2]))
    con.commit()

build_unstable_table()

for solver in cfg.samples:
    solver = str(solver)
    res = cur.execute(f"""SELECT COUNT(*) FROM {cfg.table_name}
            WHERE query_path == vanilla_path
            AND command LIKE "%{solver}%" """)
    v_count = res.fetchall()[0][0]

    res = cur.execute(f"""SELECT * FROM {unstable_table_name}
        WHERE solver = ?""", (solver, ))
    rows = res.fetchall()
    print("solver " + solver)
    maybe = 0
    for row in rows:
        shuffle_summary = ast.literal_eval(row[4])
        rename_summary = ast.literal_eval(row[5])
        sseed_summary = ast.literal_eval(row[6])
        if shuffle_summary[1] != 0 or rename_summary[1] != 0 or sseed_summary[1] != 0:
            maybe += 1

    print(f"# vanilla queries: {v_count}")
    print(f"# vanilla queries with [0, 90] success rate in any mut group: {len(rows)}")
    print(f"# vanilla queries with (0, 90] success rate in any mut group: {maybe}")
    print("")

# con = sqlite3.connect(DB_PATH)
# cur = con.cursor()
# res = cur.execute(f"""SELECT * FROM test_results""")
# for row in res.fetchall():
#     print(row[3])
#     print(row[4])
#     print(row[5])
