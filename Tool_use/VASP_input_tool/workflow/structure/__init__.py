"""
flow.workflow.structure — pymatgen structure generation and manipulation helpers.
flow.workflow.structure — pymatgen 结构生成与操作辅助工具包。

Exports / 导出内容:
  AdsorptionModify      – add/remove adsorbate sites on an existing slab
                          / 在已有 slab 上添加或移除吸附物位点
  BulkToSlabGenerator   – cleave bulk structure into surface slab models
                          / 从体相结构切割生成表面 slab 模型
  load_structure        – resolve and load a pymatgen Structure from a path
                          / 从路径解析并加载 pymatgen Structure
  get_best_structure_path – prefer CONTCAR over POSCAR in a completed dir
                            / 在已完成计算目录中优先使用 CONTCAR
  parse_supercell_matrix  – parse supercell matrix from config
                            / 从配置解析超胞矩阵
  get_atomic_layers       – group atoms into layers along a lattice vector
                            / 沿晶格矢量方向将原子分组为原子层
"""
from .adsorption import AdsorptionModify
from .slab import BulkToSlabGenerator
from .utils import get_atomic_layers, get_best_structure_path, load_structure, parse_supercell_matrix

__all__ = [
    "AdsorptionModify",
    "BulkToSlabGenerator",
    "load_structure",
    "get_best_structure_path",
    "parse_supercell_matrix",
    "get_atomic_layers",
]
