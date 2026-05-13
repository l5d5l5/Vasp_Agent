#!/bin/bash
#PBS -N {{ job_name }}
#PBS -l nodes=1:ppn={{ ppn }}:c{{ ppn }}
#PBS -l walltime={{ walltime }}
#PBS -j oe
#PBS -q {{ queue }}
ulimit -s unlimited

# ── 硬编码参数（集群固定，修改本文件而非 params.yaml）───────────────────────
VER=5.4.4
TYPE2=std
OPT=2
COMPILER=2020u2
IMPIVER=2019.8.254
VASPHOME=/data/software/vasp/compile/
VDW_KERNEL=/data/software/vasp/compile/vdw_kernel.bindat

# ── TYPE1：VASP 构建类型，由 params.yaml 的 vasp_runtime.TYPE1 指定 ──────────
# 可选值：org / beef / vtst / beefvtst
TYPE1={{ TYPE1 }}

# ── 加载编译器和 MPI 环境 ─────────────────────────────────────────────────────
source /data/opt/intel${COMPILER}/compilers_and_libraries/linux/bin/compilervars.sh intel64
export LD_LIBRARY_PATH=/data/opt/intel${COMPILER}/mkl/lib/intel64:$LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/data/opt/intel${COMPILER}/lib/intel64:$LD_LIBRARY_PATH
source /data/opt/intel${COMPILER}/impi/${IMPIVER}/intel64/bin/mpivars.sh

LOG_FILE=run.log

# ── 工作流路径（由 hook.py 自动填充，勿手动修改）────────────────────────────
PARAMS_FILE="{{ params_file }}"
STAGE="{{ stage }}"
WORKDIR="{{ workdir }}"
HOOK_SCRIPT="{{ hook_script }}"

cd "${WORKDIR}"

# ── BEEF 系泛函需要 vdw_kernel.bindat ────────────────────────────────────────
if [[ "${TYPE1}" == beef* ]]; then
    if [ ! -f vdw_kernel.bindat ]; then
        if [ ! -f "${VDW_KERNEL}" ]; then
            echo "[FATAL] TYPE1=${TYPE1} 需要 vdw_kernel.bindat，文件不存在: ${VDW_KERNEL}" >&2
            exit 30
        fi
        ln -f "${VDW_KERNEL}" vdw_kernel.bindat 2>/dev/null || cp -f "${VDW_KERNEL}" vdw_kernel.bindat
    fi
fi

# ── 若已正常收敛则跳过 VASP ──────────────────────────────────────────────────
SKIP_VASP=0
if [ -f OUTCAR ]; then
    if tail -n 80 OUTCAR | grep -qiE "total cpu time used|voluntary context switches"; then
        SKIP_VASP=1
    fi
fi

if [ "${SKIP_VASP}" -eq 0 ]; then
    mpirun ${VASPHOME}${VER}_${COMPILER}/vasp.${VER}_${TYPE1}_O${OPT}/bin/vasp_${TYPE2} > ${LOG_FILE} 2>&1
fi

# ── OUTCAR 终止检查 ───────────────────────────────────────────────────────────
if [ ! -f OUTCAR ]; then
    echo "[FATAL] OUTCAR 不存在" >> "${LOG_FILE}"
    exit 10
fi
tail -n 80 OUTCAR | grep -qiE "total cpu time used|voluntary context switches" || {
    echo "[FATAL] OUTCAR 未正常终止" >> "${LOG_FILE}"
    exit 11
}

# ── Lobster 阶段：使用环境变量 $LOBSTER_BIN ───────────────────────────────────
# 在 ~/.bashrc 或集群 module 中设置: export LOBSTER_BIN=/path/to/lobster
case "${STAGE}" in
    *_lobster)
        if [ -z "${LOBSTER_BIN}" ] || [ ! -x "${LOBSTER_BIN}" ]; then
            echo "[FATAL] 环境变量 LOBSTER_BIN 未设置或不可执行" >> "${LOG_FILE}"
            exit 20
        fi
        for f in lobsterin WAVECAR POSCAR POTCAR INCAR KPOINTS; do
            [ -s "$f" ] || { echo "[FATAL] 缺少文件: $f" >> "${LOG_FILE}"; exit 21; }
        done
        "${LOBSTER_BIN}" > lobster.log 2>&1
        [ -s lobsterout ] || { echo "[FATAL] lobsterout 缺失或为空" >> "${LOG_FILE}"; exit 22; }
        ;;
esac

# ── 清理中间文件 ──────────────────────────────────────────────────────────────
case "${STAGE}" in
    *_lobster)
        rm -f REPORT EIGENVAL IBZKPT PCDAT PROCAR XDATCAR FORCECAR || true
        ;;
    *)
        rm -f CHG* REPORT EIGENVAL IBZKPT PCDAT PROCAR WAVECAR XDATCAR FORCECAR || true
        ;;
esac

echo "run complete on $(hostname): $(date) $(pwd)" >> ~/job.log

# ── 激活 Python 环境并触发工作流下一阶段 ─────────────────────────────────────
CONDA_SH="{{ conda_sh }}"
CONDA_ENV="{{ conda_env }}"
PYTHON="{{ python_bin }}"

if [ -n "${CONDA_SH}" ] && [ -f "${CONDA_SH}" ]; then
    # shellcheck disable=SC1090
    source "${CONDA_SH}"
    [ -n "${CONDA_ENV}" ] && conda activate "${CONDA_ENV}" >/dev/null 2>&1 || true
fi
[ -z "${PYTHON}" ] && PYTHON=python

"${PYTHON}" "${HOOK_SCRIPT}" --params "${PARAMS_FILE}" mark-done --workdir "${WORKDIR}" >> "${LOG_FILE}" 2>&1
