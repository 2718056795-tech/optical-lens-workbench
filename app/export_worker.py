"""Isolated format export from a frozen saved prescription."""
import argparse
from analysis_isolation import install
def main():
 p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--format',choices=['seq','zmx'],required=True);p.add_argument('--output',required=True);a=p.parse_args()
 install('optiland')
 from optiland_bridge import export_lens
 export_lens(a.source,a.format,a.output)
if __name__=='__main__':main()
