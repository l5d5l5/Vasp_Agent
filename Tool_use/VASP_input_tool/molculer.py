import ase
from pymatgen.core import Molecule, Structure
from ase.build import molecule as ase_molecule
from pymatgen.io.ase import AseAtomsAdaptor
    

a = AseAtomsAdaptor.get_molecule(ase_molecule("C3H6"))
a.to(fmt="xyz", filename="C3H6.xyz")




