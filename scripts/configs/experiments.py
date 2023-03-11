from configs.projects import *

class Mutation(str, Enum):
    SHUFFLE = "shuffle"
    RENAME = "rename"
    # SSEED = "sseed"
    # SMT_SEED = "smt_seed"
    # SAT_SEED = "sat_seed"
    RSEED = "rseed"
    LOWER_SHUFFLE = "lower_shuffle"

    def __str__(self):
        return str.__str__(self)

class QueryExpConfig:
    def __init__(self, name, project):
        self.name = name

        assert isinstance(project, ProjectConfig)

        self.project = project

        # how many times do we run each query? default=1
        self.trials = 1

        # how many mutants to generate at most
        self.max_mutants = 60

        # how long do we wait? (seconds)
        self.timeout = 60

        self.enabled_muts = [Mutation.SHUFFLE, Mutation.RENAME, Mutation.RSEED]

    def get_solver_table_name(self, solver):
        # assert (solver in self.samples)
        return f"{self.name}_{str(solver)}"

class ExpConfig:
    def __init__(self, name, project, solvers, count=None, load_list=False):
        self.qcfg = QueryExpConfig(name, project)
        for s in solvers:
            assert isinstance(s, SolverInfo)
        # how many solver processes to run in parallel?
        self.num_procs = 7

        self.samples = dict()
        # these are the enabled solvers and their sampled queries
        if load_list:
            total = 0
            for solver in solvers:
                lname = f"data/sample_lists/{name}_{str(solver)}"
                if not os.path.isfile(lname):
                    print(f"[WARN] sample list not found: {lname}")
                else:
                    solver_samples = set()
                    for line in open(lname).readlines():
                        line = line.strip()
                        solver_samples.add(line)
                    self.samples[solver] = solver_samples
                    total += len(solver_samples)
            # print(name, total)
        else:
            self.samples = project.get_samples(solvers, count)

    def get_summary_table_name(self):
        return self.qcfg.name + "_summary"

    def get_project_name(self):
        return self.qcfg.project.name

    def empty_muts_map(self, init=[]):
        m = {str(mut): init.copy() for mut in self.qcfg.enabled_muts}
        return m

    # def set_plain_only(self):
    #     self.max_mutants = 0

    # def load_sample_list(self):
        # with open(list_path) as f:
        #     for line in f:
