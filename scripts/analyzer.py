from db_utils import *
import scipy.stats as stats
import numpy as np
import math
from tqdm import tqdm
import ast
from datetime import datetime

from configs.projects import *
from configs.experiments import *
from plot_utils import *
import matplotlib.pyplot as plt

COLORS = [
    "#FFB300", # Vivid Yellow
    "#803E75", # Strong Purple
    "#FF6800", # Vivid Orange
    "#A6BDD7", # Very Light Blue
    "#C10020", # Vivid Red
    "#CEA262", # Grayish Yellow
    "#817066", # Medium Gray
]

def append_summary_table(cfg, solver):
    con, cur = get_cursor()
    solver_table = cfg.qcfg.get_solver_table_name(solver)
    summary_table = cfg.get_summary_table_name()

    res = cur.execute(f"""
        SELECT DISTINCT(query_path), result_code, elapsed_milli
        FROM {solver_table}
        WHERE query_path = vanilla_path""")

    vanilla_rows = res.fetchall()
    for (vanilla_path, v_rcode, v_time) in tqdm(vanilla_rows):
        res = cur.execute("DROP VIEW IF EXISTS query_view");
        res = cur.execute(f"""CREATE VIEW query_view AS 
            SELECT result_code, elapsed_milli, perturbation FROM {solver_table}
            WHERE query_path != vanilla_path
            AND vanilla_path = "{vanilla_path}" """)

        results = dict()

        for perturb in cfg.qcfg.enabled_muts:
            res = cur.execute(f"""SELECT * FROM query_view
                WHERE perturbation = ?""", (perturb,))
            rows = res.fetchall()
            sample_size = len(rows)
            veri_res = [r[0] for r in rows]
            veri_times = [r[1] for r in rows]

            if sample_size == 0:
                print(f"[WARN] 0 sample size encountered: {vanilla_path}")
                results[perturb] = (0, 0, [], [])
                continue

            p = veri_res.count("unsat") / sample_size

            # get the sample standard deviation
            time_stdev = np.std(veri_times, ddof=1)
            results[perturb] = (p, time_stdev, veri_res, veri_times)

        summaries = []
        for perturb, (_, _, veri_res, veri_times) in results.items():
            summary = (str(perturb), veri_res, veri_times)
            summaries.append(summary)
        cur.execute(f"""INSERT INTO {summary_table}
            VALUES(?, ?, ?, ?, ?);""", 
            (str(solver), vanilla_path, v_rcode, v_time, str(summaries)))
    con.commit()
    con.close()

def build_summary_table(cfg):
    con, cur = get_cursor()
    summary_table = cfg.get_summary_table_name()

    cur.execute(f"""DROP TABLE IF EXISTS {summary_table}""")

    cur.execute(f"""CREATE TABLE {summary_table} (
        solver varchar(10),
        vanilla_path TEXT,
        v_result_code varchar(10),
        v_elapsed_milli INTEGER,
        summaries TEXT)""")

    con.commit()
    con.close()

    for solver in cfg.samples:
        append_summary_table(cfg, solver)

def as_seconds(milliseconds):
    return milliseconds / 1000

def group_time_mean(times):
    assert len(times) != 0
    return as_seconds(np.mean(times))

def group_time_std(times):
    assert len(times) != 0
    return as_seconds(np.std(times))

def group_success_rate(vres):
    assert len(vres) != 0
    return vres.count("unsat") * 100 / len(vres)

def load_summary(cfg):
    con, cur = get_cursor()
    summary_table_name = cfg.get_summary_table_name()
    summaries = dict()
    for solver in cfg.samples:
        solver = str(solver)
        res = cur.execute(f"""SELECT * FROM {summary_table_name}
            WHERE solver = ?""", (solver,))
        rows = res.fetchall()
        nrows = []
        for row in rows:
            nrow = list(row)
            nrow[4] = ast.literal_eval(row[4])
            nrows.append(nrow)
        summaries[solver] = nrows
    con.close()
    return summaries

def plot_basic(cfg, solver_summaries):
    solver_count = len(cfg.samples)
    time_figure, time_aixs = setup_fig(solver_count, 2)
    result_figure, result_aixs = setup_fig(solver_count, 2)

    for i, (solver, rows) in enumerate(solver_summaries.items()):
        means = cfg.empty_muts_map()
        stds = cfg.empty_muts_map()
        srs = cfg.empty_muts_map()

        for row in rows:
            row_summaries = row[4]
            for (perturb, vres, times) in row_summaries:
                if len(times) == 0:
                    continue
                assert len(vres) == len(times)
                means[perturb].append(group_time_mean(times))
                stds[perturb].append(group_time_std(times))
                srs[perturb].append(group_success_rate(vres))
        if solver_count != 1:
            plot_time_overall(time_aixs, means, stds, solver)
            plot_result_overall(result_aixs, srs, solver)
        else:
            plot_time_overall(time_aixs[i], means, stds, solver)
            plot_result_overall(result_aixs[i], srs, solver)
    name = cfg.qcfg.name
    save_fig(time_figure, f"{name}", f"fig/time_overall/{name}.png")
    save_fig(result_figure, f"{name}", f"fig/result_overall/{name}.png")

def get_all_sr(plain_res, summaries):
    # consider the plain one as well
    all_vres = [plain_res]
    for (_, vres, _) in summaries:
        all_vres += vres
    return group_success_rate(all_vres)

def get_categories(solver_summaries):
    categories = dict()
    for solver, rows in solver_summaries.items():
        unsolvables, stables, unstables = set(), set(), set()
        count = 0
        for row in rows:
            summaries = row[4]
            plain_path, plain_res = row[1], row[2]
            all_sr = get_all_sr(plain_res, summaries)
            if all_sr == 100:
                stables.add(plain_path)
            elif all_sr == 0:
                unsolvables.add(plain_path)
            else:
                unstables.add(plain_path)
            count += 1
        categories[solver] = (unsolvables, stables, unstables, count)
    return categories

def get_unstable_intervals(solver_summaries):
    categories = get_categories(solver_summaries)
    intervals = dict()

    for solver, (unsolvables, stables, _, count) in categories.items():
        max_ratio = (count - len(stables)) * 100 / count
        min_ratio = len(unsolvables) * 100 / count
        intervals[solver] = (min_ratio, max_ratio)
    return intervals

def plot_time_stable(cfg, solver_summaries):
    solver_count = len(cfg.samples)
    time_figure, time_aixs = setup_fig(solver_count, 1)

    for i, (solver, rows) in enumerate(solver_summaries.items()):
        stds = cfg.empty_muts_map()
        for row in rows:
            summaries = row[4]
            plain_path, plain_res = row[1], row[2]
            all_sr = get_all_sr(plain_res, summaries)
            if all_sr != 100:
                continue
            for (perturb, _, times) in summaries:
                if len(times) == 0:
                    continue
                stds[perturb].append(group_time_std(times))
        sp = time_aixs[i]
        for perturb, values in stds.items():
            xs, ys = get_cdf_pts(values)
            sp.set_ylabel("cumulative probability")
            sp.plot(xs, ys, marker=",", label=perturb)
            sp.set_title(f'{solver} stable query standard deviation cdf')
        name = cfg.qcfg.name
        save_fig(time_figure, f"{name}", f"fig/time_stable/{name}.png")

def plot_time_mixed(cfg, solver_summaries):
    solver_count = len(cfg.samples)
    time_figure, time_aixs = setup_fig(solver_count, 1)

    for i, (solver, rows) in enumerate(solver_summaries.items()):
        means = cfg.empty_muts_map()
        for row in rows:
            summaries = row[4]
            plain_path, plain_res = row[1], row[2]
            all_sr = get_all_sr(plain_res, summaries)
            if all_sr == 100 or all_sr == 0:
                continue
            for (perturb, vres, times) in summaries:
                nts = [times[i] for i, x in enumerate(vres) if x != "timeout"]
                if len(nts) == 0:
                    continue
                means[perturb].append(group_time_mean(nts))
        sp = time_aixs[i]
        for perturb, values in means.items():
            xs, ys = get_cdf_pts(values)
            sp.set_ylabel("cumulative probability")
            sp.set_xlabel("mean response time (success only)")
            sp.plot(xs, ys, marker=",", label=perturb)
            sp.set_title(f'{solver} mixed queries cdf')
        name = cfg.qcfg.name
        save_fig(time_figure, f"{name}", f"fig/time_mixed/{name}.png")

# def str_percent(p):
#     if np.isnan(p):
#         return "-"
#     return str(round(p, 2)) + "%"

# def str_interval(interval):
#     return f"{str_percent(interval[0])}, {str_percent(interval[1])}"

# def print_summary_data(cfgs):
#     rows = []
#     for cfg in cfgs:
#         # print(cfg.get_project_name())
#         row = []
#         intervals = plot_result_overall(cfg)
#         bounds = plot_time_overall(cfg)
#         for solver in ALL_SOLVERS:
#             item = [np.nan, np.nan, np.nan]
#             if solver in intervals:
#                 item[0] = intervals[solver][0]
#                 item[1] = intervals[solver][1]
#             if solver in bounds:
#                 item[2] = bounds[solver]
#             row.append(item)
#         rows.append(row)
#     print(rows)

def as_md_row(row):
    return "|" + "|".join(row) + "|"

def as_md_table(table):
    lines = [as_md_row(table[0])]
    lines.append("|:---------:" * (len(table[0])) + "|")
    for row in table[1:]:
        lines.append(as_md_row(row))
    lines.append("\n")
    return "\n".join(lines)

def plot_query_sizes(cfgs):
    import os
    figure, axis = setup_fig(1, 2)
    colors = [
        "#FFB300", # Vivid Yellow
        "#803E75", # Strong Purple
        "#FF6800", # Vivid Orange
        "#A6BDD7", # Very Light Blue
        "#C10020", # Vivid Red
        "#CEA262", # Grayish Yellow
        "#817066", # Medium Gray
    ]
    for i, cfg in enumerate(cfgs):
        clean_dir = cfg.qcfg.project.clean_dirs[Z3_4_11_2]
        paths = list_smt2_files(clean_dir)
        sizes = [] 
        for path in paths:
            sizes.append(os.path.getsize(path) / (8 * 1024 * 1024))
        # plot_csum(plt, sizes, )
        n = len(sizes)
        axis[0].plot(np.sort(sizes), np.arange(n), marker=",", label=cfg.qcfg.name, color=colors[i])
        xs, ys = get_cdf_pts(sizes)
        axis[1].plot(xs, ys, marker=",", label=cfg.qcfg.name, color=colors[i])

    axis[0].legend()
    axis[0].set_ylabel("cumulative probability")
    axis[0].set_xlabel("query size (mb)")

    axis[1].legend()
    axis[1].set_xlabel("query size (mb)")

    plt.tight_layout()
        # plt.plot(xs, ys, marker=",", label=cfg.qcfg.name)
    save_fig(figure, f"sizes", f"fig/sizes.pdf")

def analyze_cond_fail(cfg):
    con, cur = get_cursor()
    summary_table_name = cfg.get_summary_table_name()
    print(cfg.get_project_name())

    f = open("fig/cond_fail/" + summary_table_name + ".md", "w+")

    for i, solver in enumerate(cfg.samples):
        solver = str(solver)
        # print(solver, cfg.get_project_name())
        res = cur.execute(f"""SELECT * FROM {summary_table_name}
            WHERE solver = ?""", (solver, ))
        rows = res.fetchall()

        unsolvable = {p: set() for p in cfg.qcfg.enabled_muts}
        unsolvable["plain"] = set()

        for row in rows:
            if row[2] != "unsat":
                unsolvable["plain"].add(row[1])

            summaries = ast.literal_eval(row[4])
            for (perturb, vres, _) in summaries:
                if len(vres) != 0 and vres.count("unsat") ==0:
                    unsolvable[perturb].add(row[1])

        muts = ["plain", "shuffle", "rename", "sseed"]
        table = [[solver] + [m + "(" + str(len(unsolvable[m])) + ")" for m in muts]]

        for p1 in muts:
            row = [p1 + "(" + str(len(unsolvable[p1])) + ")"]
            for p2 in muts:
                us1 = unsolvable[p1]
                us2 = unsolvable[p2]
                inter = len(us1.intersection(us2))
                if p1 == p2:
                    row.append("-")
                if len(us1) == 0:
                    row.append(f"nan")
                else:
                    row.append(f"{inter}({str(round(inter * 100 / len(us1), 2))})")
            table.append(row)
        f.write(as_md_table(table))
    con.close()

# def print_as_md_table(cfgs, summary_rows):
#     solver_names = [str(s) for s in ALL_SOLVERS]
#     project_names = [cfg.get_project_name() for  cfg in cfgs]

#     row = [" "] + solver_names
#     print("|" + "|".join(row) + "|")
#     print("|:---------:" * (len(ALL_SOLVERS) + 1) + "|")
#     for i, project in enumerate(project_names):
#         row = [project]
#         for (lp, hp, p) in summary_rows[i]:
#             row.append(f"{str_percent(lp)}~{str_percent(hp)}, {str_percent(p)}")
#         print("|" + "|".join(row) + "|")

def dump_all(cfgs):
    projects = [cfg.qcfg.project for  cfg in cfgs]
    project_names = [cfg.get_project_name() for  cfg in cfgs]
    solver_names = [str(s) for s in ALL_SOLVERS]

    nan = np.nan

    data = [[[0.38809831824062097, 1.6817593790426908, 4.139715394566624], [0.38809831824062097, 1.6817593790426908, 3.4928848641655885], [0.6468305304010349, 1.1642949547218628, 0.6468305304010349], [0.129366106080207, 0.7761966364812419, 2.5873221216041395], [0.517464424320828, 1.423027166882277, 4.786545924967658], [1.034928848641656, 1.034928848641656, 0]], [[2.044790652385589, 3.554040895813048, 4.284323271665044], [1.9474196689386563, 3.456669912366115, 4.33300876338851], [1.9474196689386563, 3.6514118792599803, 4.430379746835443], [6.815968841285297, 9.444985394352482, 6.621226874391431], [5.150631681243926, 8.309037900874635, 7.337220602526725], [85.34566699123661, 86.31937682570594, 1.2171372930866602]], [[1.483568075117371, 2.4976525821596245, 0.863849765258216], [1.5023474178403755, 2.3661971830985915, 0.7699530516431925], [0.9577464788732394, 1.9154929577464788, 1.0704225352112675], [nan, nan, nan], [1.6150234741784038, 4.356807511737089, 2.572769953051643], [nan, nan, nan]], [[1.6524216524216524, 1.8233618233618234, 0.17094017094017094], [1.7094017094017093, 1.8803418803418803, 0.11396011396011396], [2.507122507122507, 2.507122507122507, 0.05698005698005698], [2.507122507122507, 2.5641025641025643, 0.11396011396011396], [2.507122507122507, 2.6210826210826212, 0.11396011396011396], [nan, nan, nan]], [[1.4642857142857142, 2.1607142857142856, 1.7142857142857142], [1.4642857142857142, 2.1785714285714284, 1.7857142857142858], [1.3214285714285714, 2.4642857142857144, 2.1964285714285716], [1.1607142857142858, 1.9464285714285714, 1.625], [1.5357142857142858, 5.071428571428571, 5.428571428571429], [nan, nan, nan]], [[3.5807291666666665, 4.4921875, 3.9713541666666665], [3.5807291666666665, 4.557291666666667, 4.296875], [3.7760416666666665, 4.427083333333333, 4.4921875], [2.6041666666666665, 3.2552083333333335, 3.125], [3.2552083333333335, 3.90625, 3.6458333333333335], [nan, nan, nan]]]

    # # # print_as_md_table(data)
    total = len(solver_names) * len(project_names)
    barWidth = len(solver_names)/50
    # fig = plt.subplots(figsize=(total, 8))
    fig = plt.figure()

    br = np.arange(len(solver_names))
    br = [x - barWidth for x in br]

    colors = [
        "#FFB300", # Vivid Yellow
        "#803E75", # Strong Purple
        "#FF6800", # Vivid Orange
        "#A6BDD7", # Very Light Blue
        "#C10020", # Vivid Red
        "#CEA262", # Grayish Yellow
        "#817066", # Medium Gray
    ]

    for pi, project_row in enumerate(data):
        lps = []
        hps = []
        br = [x + barWidth for x in br]
        pcolor = colors[pi]
        pds = []
        patterns = []
        for i, (lp, hp, p) in enumerate(project_row):
            if np.isnan(lp):
                lp = 0
            if np.isnan(hp):
                hp = 0
            if not np.isnan(p):
                pds.append(p)
            else:
                pds.append(-1)
            if lp == hp and lp != 0:
                plt.scatter(br[i], lp, marker='_', color=pcolor, s=80)
            lps.append(lp)
            hps.append(hp)
            if projects[pi].orig_solver == ALL_SOLVERS[i]:
                plt.bar(br[i], hp-lp, bottom=lp, width = barWidth, color=pcolor, edgecolor='black')
                # patterns.append('\\')
            else:
                patterns.append(None)

        hps_ = [hps[i] - lps[i] for i in range(len(hps))]
        plt.bar(br, lps, width = barWidth, color=pcolor, alpha=0.20)
        plt.bar(br, hps_, bottom=lps, width = barWidth, label=project_names[pi], color=pcolor)
        plt.scatter(br, pds, marker='x', s=20, color='black', zorder=3)

    plt.ylim(bottom=0, top=15)
    plt.xlabel('solvers', fontsize = 15)
    plt.ylabel('unstable ratios', fontsize = 15)
    plt.xticks([r + barWidth for r in range(len(lps))], solver_names, rotation=30, ha='right')
    plt.legend()
    plt.tight_layout()
    plt.savefig("fig/all.pdf")

# dump_all(cfgs)
# print_summary_data(cfgs)
# for cfg in cfgs:
#     plot_time_mixed(cfg)
#     plot_time_success(cfg)
# plot_query_sizes(cfgs)
# build_summary_table(D_KOMODO_BASIC_CFG)
# append_summary_table(cfg, Z3_4_6_0)
