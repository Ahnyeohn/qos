#!/usr/bin/env python3

import argparse

import datetime

import os

import re

import signal

import subprocess

import sys

import time

# ============================================================

# SFU event tags.

# ============================================================

COLD_NETWORK_EVENT = "[KNN-COLD-NETWORK-PAUSE-ENTER]"

KNN_NETWORK_EVENT = "[KNN-EVAL-NETWORK-PAUSE-ENTER]"

EXPERIMENT_COMPLETE_EVENT = "[KNN-EXPERIMENT-COMPLETE]"

# SFU log:

#

#   from:NORMAL to:2MBIT

#   from:2MBIT to:LOSS_5PCT

#   from:LOSS_5PCT to:NORMAL

#

# ':' / '=' 둘 다 허용.

TARGET_RE = re.compile(

    r"\bto\s*[:=]\s*(NORMAL|2MBIT|4MBIT|6MBIT|8MBIT|LOSS_2PCT|LOSS_5PCT|LOSS_15PCT)\b"

)

def now_string():

    return datetime.datetime.now().strftime(

        "%Y-%m-%d %H:%M:%S.%f"

    )[:-3]

class ExperimentController:

    def __init__(

        self,

        interface,

        sfu_log_path,

        controller_log_path,

        sfu_command,

        sfu_user,

        network_option,

    ):

        self.interface = interface

        self.sfu_log_path = sfu_log_path

        self.controller_log_path = controller_log_path

        self.sfu_command = sfu_command

        self.sfu_user = sfu_user

        self.network_option = network_option

        self.current_profile = None

        self.sfu_process = None

        self.experiment_complete = False

        self.sfu_log_file = None

    # ========================================================

    # Logging.

    # ========================================================

    def log(self, message):

        line = f"[{now_string()}] {message}"

        print(line, flush=True)

        with open(

            self.controller_log_path,

            "a",

            buffering=1,

        ) as f:

            f.write(line + "\n")

    # ========================================================

    # Command helper.

    # ========================================================

    def run_command(

        self,

        command,

        allow_failure=False,

    ):

        self.log(

            "EXEC: " + " ".join(command)

        )

        result = subprocess.run(

            command,

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE,

            text=True,

        )

        if result.stdout.strip():

            self.log(

                "STDOUT: " +

                result.stdout.strip()

            )

        if result.returncode != 0:

            if allow_failure:

                self.log(

                    f"IGNORED rc={result.returncode}: "

                    + result.stderr.strip()

                )

                return False

            self.log(

                f"ERROR rc={result.returncode}: "

                + result.stderr.strip()

            )

            raise RuntimeError(

                "command failed: "

                + " ".join(command)

            )

        if result.stderr.strip():

            self.log(

                "STDERR: " +

                result.stderr.strip()

            )

        return True

    # ========================================================

    # tc profiles.

    # ========================================================

    def show_qdisc(self):

        result = subprocess.run(

            [

                "tc",

                "qdisc",

                "show",

                "dev",

                self.interface,

            ],

            stdout=subprocess.PIPE,

            stderr=subprocess.PIPE,

            text=True,

        )

        if result.stdout.strip():

            self.log(

                "QDISC: " +

                result.stdout.strip()

            )

    def apply_normal(self, force=False):

        if (

            not force

            and self.current_profile == "NORMAL"

        ):

            self.log(

                "SKIP duplicate profile: NORMAL"

            )

            return

        self.log(

            "APPLY NETWORK PROFILE: NORMAL"

        )

        # qdisc가 없는 경우 실패할 수 있으므로 허용.

        self.run_command(

            [

                "tc",

                "qdisc",

                "del",

                "dev",

                self.interface,

                "root",

            ],

            allow_failure=True,

        )

        self.current_profile = "NORMAL"

        self.show_qdisc()

    def apply_limited_profile(self, profile, rate):

        if self.current_profile == profile:

            self.log(f"SKIP duplicate profile: {profile}")

            return



        self.log(f"APPLY NETWORK PROFILE: {profile}")



        # Bandwidth만 제한한다.

        #

        # 기존 TBF의 작은 burst/limit가 video frame burst 자체를

        # 추가로 drop시키는 영향을 피하기 위해 netem rate를 사용한다.

        # profile별 차이는 rate(1/2/4/8mbit)뿐이다.

        # self.run_command(

        #     [

        #         "tc",

        #         "qdisc",

        #         "replace",

        #         "dev",

        #         self.interface,

        #         "root",

        #         "netem",

        #         "rate",

        #         rate,

        #     ]

        # )



        self.run_command(

            [

                "tc",

                "qdisc",

                "replace",

                "dev",

                self.interface,

                "root",

                "tbf",

                "rate",

                rate,

                "burst",

                "64kb",

                "limit",

                "512kb",

            ]

        )



        self.current_profile = profile

        self.show_qdisc()

    def apply_loss_profile(self, profile, loss_percent):

        if self.current_profile == profile:

            self.log(f"SKIP duplicate profile: {profile}")

            return

        self.log(f"APPLY NETWORK PROFILE: {profile}")

        # Loss-only profile.
        # Bandwidth shaping은 제거되고 netem loss만 root qdisc에 적용된다.
        self.run_command(
            [
                "tc",
                "qdisc",
                "replace",
                "dev",
                self.interface,
                "root",
                "netem",
                "loss",
                loss_percent,
            ]
        )

        self.current_profile = profile

        self.show_qdisc()

    def apply_profile(self, profile):

        if profile == "NORMAL":

            self.apply_normal()

        elif profile == "6MBIT":

            self.apply_limited_profile("6MBIT", "6mbit")

        elif profile == "2MBIT":

            self.apply_limited_profile("2MBIT", "2mbit")

        elif profile == "4MBIT":

            self.apply_limited_profile("4MBIT", "4mbit")

        elif profile == "8MBIT":

            # Legacy profile support.
            self.apply_limited_profile("8MBIT", "8mbit")

        elif profile == "LOSS_2PCT":

            self.apply_loss_profile("LOSS_2PCT", "2%")

        elif profile == "LOSS_5PCT":

            self.apply_loss_profile("LOSS_5PCT", "5%")

        elif profile == "LOSS_15PCT":

            self.apply_loss_profile("LOSS_15PCT", "15%")

        else:

            raise RuntimeError(f"unknown profile: {profile}")

    # ========================================================

    # SFU process management.

    # ========================================================

    def start_sfu(self):

        self.log(

            "STARTING SFU"

        )

        self.log(

            f"SFU COMMAND: {self.sfu_command}"

        )

        # 매 실험마다 새로운 sfu.log.

        self.sfu_log_file = open(

            self.sfu_log_path,

            "w",

            buffering=1,

        )

        # Controller는 root로 실행하지만

        # SFU는 기존 사용자 계정으로 실행.

        #

        # start_new_session=True:

        # SFU와 그 자식 process들을 하나의 process group으로 묶음.

        #

        # npm -> node -> mediasoup worker까지

        # 같은 process group이면 한번에 종료 가능.

        launch_command = (

            f"export KNN_NETWORK_OPTION={self.network_option}; "

            f"{self.sfu_command}"

        )

        command = [

            "sudo",

            "-u",

            self.sfu_user,

            "bash",

            "-lc",

            launch_command,

        ]

        self.sfu_process = subprocess.Popen(

            command,

            stdout=subprocess.PIPE,

            stderr=subprocess.STDOUT,

            text=True,

            bufsize=1,

            # 매우 중요.

            start_new_session=True,

        )

        self.log(

            f"SFU STARTED pid={self.sfu_process.pid}"

        )

    def stop_sfu(self):

        if self.sfu_process is None:

            return

        if self.sfu_process.poll() is not None:

            self.log(

                f"SFU already exited "

                f"rc={self.sfu_process.returncode}"

            )

            return

        self.log(

            "STOPPING SFU: SIGTERM"

        )

        try:

            # SFU process group 전체 종료.

            #

            # npm / node / mediasoup worker 등

            # 자식 process까지 함께 종료하기 위함.

            os.killpg(

                os.getpgid(self.sfu_process.pid),

                signal.SIGTERM,

            )

        except ProcessLookupError:

            self.log(

                "SFU process already gone"

            )

            return

        try:

            self.sfu_process.wait(

                timeout=10

            )

            self.log(

                f"SFU EXITED rc="

                f"{self.sfu_process.returncode}"

            )

        except subprocess.TimeoutExpired:

            self.log(

                "SFU did not exit after 10 sec "

                "-> SIGKILL"

            )

            try:

                os.killpg(

                    os.getpgid(

                        self.sfu_process.pid

                    ),

                    signal.SIGKILL,

                )

            except ProcessLookupError:

                pass

            self.sfu_process.wait()

            self.log(

                "SFU killed with SIGKILL"

            )

    # ========================================================

    # SFU event processing.

    # ========================================================

    def handle_network_event(self, line):

        match = TARGET_RE.search(line)

        if not match:

            self.log(

                "WARNING: network pause event "

                "found but target profile "

                "could not be parsed"

            )

            return

        target = match.group(1)

        self.log(

            f"NETWORK TARGET: {target}"

        )

        self.apply_profile(target)

        self.log(

            f"TC APPLY SUCCESS: {target}"

        )

    def handle_sfu_line(self, line):

        # ====================================================

        # Cold Start network transition.

        # ====================================================

        if COLD_NETWORK_EVENT in line:

            self.log(

                "COLD NETWORK EVENT: " +

                line

            )

            self.handle_network_event(line)

            return

        # ====================================================

        # KNN evaluation network transition.

        # ====================================================

        if KNN_NETWORK_EVENT in line:

            self.log(

                "KNN NETWORK EVENT: " +

                line

            )

            self.handle_network_event(line)

            return

        # ====================================================

        # Entire experiment complete.

        # ====================================================

        if EXPERIMENT_COMPLETE_EVENT in line:

            self.log(

                "EXPERIMENT COMPLETE EVENT: " +

                line

            )

            self.experiment_complete = True

            return

    # ========================================================

    # Main experiment loop.

    # ========================================================

    def run(self):

        self.log(

            "============================================================"

        )

        self.log(

            "EXPERIMENT CONTROLLER START"

        )

        self.log(

            f"interface={self.interface}"

        )

        self.log(

            f"sfuUser={self.sfu_user}"

        )

        self.log(

            f"networkOption={self.network_option}"

        )

        try:

            # ------------------------------------------------

            # 모든 실험은 NORMAL에서 시작.

            # ------------------------------------------------

            self.apply_normal(force=True)

            # ------------------------------------------------

            # SFU 실행.

            # ------------------------------------------------

            self.start_sfu()

            # ------------------------------------------------

            # SFU stdout을 직접 읽음.

            #

            # 별도의 tail -F / tee 필요 없음.

            # ------------------------------------------------

            for raw_line in self.sfu_process.stdout:

                line = raw_line.rstrip("\n")

                # 원본 SFU log 저장.

                self.sfu_log_file.write(

                    line + "\n"

                )

                self.sfu_log_file.flush()

                # 관심 event 처리.

                self.handle_sfu_line(line)

                # --------------------------------------------

                # SFU가 실험 종료를 알려줌.

                # --------------------------------------------

                if self.experiment_complete:

                    self.log(

                        "experiment complete "

                        "-> terminate SFU"

                    )

                    break

            # 정상 실험 완료.

            if self.experiment_complete:

                self.stop_sfu()

            else:

                # SFU가 먼저 죽은 상황.

                rc = self.sfu_process.poll()

                self.log(

                    "WARNING: SFU exited before "

                    "experiment complete "

                    f"rc={rc}"

                )

        finally:

            # ------------------------------------------------

            # 어떤 방식으로 끝나든 network는 NORMAL 복구.

            # ------------------------------------------------

            self.log(

                "FINAL CLEANUP: restore NORMAL"

            )

            self.apply_normal(force=True)

            # process가 남아 있으면 정리.

            self.stop_sfu()

            if self.sfu_log_file:

                self.sfu_log_file.flush()

                self.sfu_log_file.close()

            self.log(

                "EXPERIMENT CONTROLLER STOP"

            )

def validate_environment(interface):

    if os.geteuid() != 0:

        print(

            "ERROR: controller must run as root.\n"

            "Use:\n"

            "  sudo python3 experiment_controller.py ...",

            file=sys.stderr,

        )

        sys.exit(1)

    if not os.path.exists(

        f"/sys/class/net/{interface}"

    ):

        print(

            f"ERROR: interface not found: "

            f"{interface}",

            file=sys.stderr,

        )

        sys.exit(1)

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(

        "--interface",

        required=True,

    )

    parser.add_argument(

        "--sfu-command",

        required=True,

        help=(

            "SFU launch command. "

            "Example: "

            "'cd /home/n2sl/.../server && npm start'"

        ),

    )

    parser.add_argument(

        "--sfu-user",

        default=os.environ.get(

            "SUDO_USER",

            os.environ.get("USER", "n2sl"),

        ),

    )

    parser.add_argument(

        "--sfu-log",

        default="./sfu.log",

    )

    parser.add_argument(

        "--controller-log",

        default="./experiment_controller.log",

    )

    parser.add_argument(

        "--network-option",

        choices=["A", "B", "C", "D", "E", "F", "G", "H"],

        default="A",

        help=(

            "A=NORMAL+2MBIT, "

            "B=NORMAL+4MBIT, "

            "C=NORMAL+2MBIT+4MBIT, "

            "D=NORMAL+2MBIT+4MBIT+6MBIT, "

            "E=NORMAL+LOSS_2PCT, "

            "F=NORMAL+LOSS_5PCT, "

            "G=NORMAL+LOSS_15PCT, "

            "H=NORMAL+2MBIT+4MBIT+LOSS_5PCT"

        ),

    )

    args = parser.parse_args()

    validate_environment(

        args.interface

    )

    controller = ExperimentController(

        interface=args.interface,

        sfu_log_path=args.sfu_log,

        controller_log_path=args.controller_log,

        sfu_command=args.sfu_command,

        sfu_user=args.sfu_user,

        network_option=args.network_option,

    )

    try:

        controller.run()

    except KeyboardInterrupt:

        controller.log(

            "CTRL-C received"

        )

if __name__ == "__main__":

    main()
