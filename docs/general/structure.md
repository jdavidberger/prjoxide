# Overview

At it's most basic level, the nexus (and most other FPGAs) is composed of basic elements (BELs), pins, wires and 
Programmable Interconnect Points (PIPs). The bitstream configures the BELs and which PIPs are active.

Loosely speaking, on the lattice components each BEL corresponds to a site. The internal tooling for lattice refers to 
wires as nodes and the terms are used interchangeably. 

The lattice parts overlay a tile grid over this structure. Largely speaking the tile grid informs on where the component
might be on the chip, but also where the configuration data can be found / specified for any given chip. 

## Sites (BELs)

Every site has a type, and the type dictates both it's pin capabilities and what programmable options and modes exist for
that given site. Sites correspond most closely to the primitives found in lattice documentation, but sometimes a site
isn't directly translated as a primitive, and instead has multiple modes which map the same site to multiple primitives
as defined in the manual.

Nearly every site name contains a prefix indicating the row and column it is most aligned to, and that tile is used to 
configure that site. A tile can have multiple sites in it, or the same site type can occur in multiple tile types where
it's configuration bits occur at different offsets. 

Many exceptions do exist where a site is named for one row-column pair but it's configuration lives in another tile, and
that tile has the appropriate tile type. For instance, LRAM's typically are like this. Part of what the fuzzers are configured
for is to represent the mapping between the site tile location and the config tile location. 

## Nodes (Wires) and PIPs

Nodes represent physical wires with gates connecting it to other nodes. Nodes can have pins tied directly onto them.

Lattice has a TCL library exposed in a tool -- lapie / lark depending on version -- which can be used to query the node 
graph. This tooling gives you which PIPs and pins are associated with the node, as well as what aliases are associated
with it. 

In terms of scale, there are about 1.7 million nodes on the LIFCL-40 part.

Nodes also have aliases. The typical reason for this is that nodes can span multiple tiles, and so each tile has a local
name for that node. Only the primary name associated with the node is directly queryable, so there is no robust way in 
general to determine every node that is associated with a given tile.

### Node Naming

Nodes have a semantically meaningful structure to their naming. They are all prefixed with `R<r>C<c>_` which gives a hint
to it's location; although nodes can span multiple tiles.

After that there are the following naming conventions:

## Tile types

Tiles of a given tile type will always have the same set of:

- Sites
- Nodes
- PIPs

Often they will also dictate the relationship between neighboring tiles in a rigid way. For instance, LRAM instances
have an associated `CIB_LR` tiletype at an offset determined by it's tiletype. 

Tile types also are the fundamental building block to configuring the chip since it rigidly maps the bits in it's 
configuration bits to the sites and pips associated with it. 

Tile types are also standard across devices -- the way you configure a PLC tile is identical in LIFCL-17 as it is in LIFCL-40,
for instance. It should be noted though that lattice is inconsistent with this principal, and so some tile types are
flagged and changed when the tilegrid is imported from lattice's interchange format. 

## Global Routes

PLC -> Branch Tap -> Branch Node -> Spine -> HROW

There is a global distribution network on the LIFCL devices which is laid out as follows:

- 