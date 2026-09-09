---
diataxis: reference
nvsf_generated: contracts/crosswalk/
---

# Crosswalks to NRM v0.1

:::{admonition} Generated page
:class: generated-page

This page is generated from `contracts/crosswalk/` by `bin/gen-docs-reference.py`. Edits here are lost on the
next build, and CI fails if the two disagree — change the source.
:::

A crosswalk states how one external system's model maps onto NRM, in which direction, and what it cannot carry. Each one is validated against both its own schema and the NRM schemas at application startup.

## Systems

| System | Role | Entities | Fields | Documented gaps |
|---|---|---|---|---|
| [`bcm-netautogen`](#bcm-netautogen) | planning input | 4 | 31 | 9 |
| [`cyclonedx`](#cyclonedx) | export target | 2 | 12 | 7 |
| [`dcgm`](#dcgm) | telemetry | 2 | 7 | 5 |
| [`nautobot`](#nautobot) | source of record | 6 | 54 | 16 |
| [`redfish`](#redfish) | discovery | 4 | 25 | 13 |
| [`ufm`](#ufm) | discovery | 4 | 26 | 7 |

## `bcm-netautogen`

**Role:** planning input

**Authority:** Authoritative for INTENT: what was ordered, what is meant to be racked where, and what is meant
to be cabled to what. Says nothing about reality -- a rack inventory file is correct until the
first substitution at the factory, and the P2P file is correct until the first cable goes into
the adjacent cage.


**Join key:** `identifiers[format=SERIAL].value` ↔ `serial`

**Not mapped:** `resource-type`, `domain`, `cooling-path`

### resource ↔ `rack inventory row / netautogen node object` (both)

One row per node. The file is per-rack, so rack identity comes from the filename or a header
cell rather than from the row -- an importer must carry it in, and getting this wrong silently
merges two racks into one.


| NRM field | System field | Notes |
|---|---|---|
| `name` | `hostname` |  |
| `identifiers[format=SERIAL].value` | `serial` |  |
| `parent_id` | `rack` | via `resolve_rack_by_name` |
| `location_id` | `rack + rack_unit` | via `resolve_location` |
| `resource_type_id` | `model` | via `resolve_type_by_model` |
| `lifecycle` | `_constant` | via `constant_planned` — Everything from a planning file is `planned` until something observes it. Importing it as `active` would make an empty data hall look fully deployed, which is precisely the kind of false confidence this contract exists to prevent. |
| `observation` | `_constant` | via `constant_expected` |
| `identifiers[format=MACAddress].value` | `bmc_mac` | Present in netautogen output because it is what PXE and BMC discovery match on. This is the earliest identifier that survives into the observed world, which makes it the most valuable field in the file for reconciliation. |
| `attributes.bmc_ip` | `bmc_ip` |  |
| `external_refs.bcm` | `node_id` |  |

**Cannot be carried:**

`domain_id`
: netautogen emits a category or configuration overlay name, which is close to a compute domain but not the same thing. Mapping it automatically would create a domain per configuration variant rather than per logical grouping.
`part_location`
: The inventory file addresses a node by rack unit, not by position within a chassis. For NVL72 trays this is adequate; for anything inside a tray it is not.

### port ↔ `P2P cabling file endpoint column` (import)

Ports are IMPLIED by the cabling file rather than listed in it: each row names two endpoints,
and each endpoint is a port that must exist. Importing the cabling file therefore creates
ports as a side effect, and an endpoint naming a port the ResourceType has no template for is
a real finding -- it means the plan cables a port the hardware does not have.


| NRM field | System field | Notes |
|---|---|---|
| `name` | `src_port / dst_port` |  |
| `resource_id` | `src_host / dst_host` | via `resolve_by_hostname` |
| `port_class` | `link_type` | via `p2p_class_map` |
| `speed_gbps` | `speed` | via `parse_speed` |
| `media` | `cable_type` | via `p2p_media_map` |
| `observation` | `_constant` | via `constant_expected` |

**Cannot be carried:**

`breakout_of`
: P2P files express breakouts inconsistently -- sometimes as a suffixed port name, sometimes as multiple rows against one cage. Requires site-specific parsing, so it is left to the importer rather than declared as a portable mapping.
`identifiers[]`
: Port-level identity is not knowable before power-on. Port GUIDs and MACs arrive from discovery and are attached during reconciliation.

### link ↔ `P2P cabling file row` (both)

One row, one expected link. This is the single most valuable import in the contract: it is the
only statement of intended topology that exists, and without it "observed" has nothing to be
compared against and a fabric sweep is just a list.


| NRM field | System field | Notes |
|---|---|---|
| `key` | `src_host_src_port : dst_host_dst_port` | via `link_key` |
| `a_port_id` | `src_host + src_port` | via `resolve_port` |
| `b_port_id` | `dst_host + dst_port` | via `resolve_port` |
| `link_class` | `link_type` | via `p2p_class_map` |
| `speed_gbps` | `speed` | via `parse_speed` |
| `cable.length_m` | `cable_length` | via `parse_length` |
| `cable.part_number` | `cable_pn` |  |
| `cable.cable_type` | `cable_type` |  |
| `observation` | `_constant` | via `constant_expected` |

**Cannot be carried:**

`operational_state`
: A plan has no operational state. Leaving it unset rather than defaulting to `unknown` is deliberate: an expected link with a state field would invite a consumer to read it.
`supporting_link_id`
: P2P files list physical cables. NVLink logical topology within an NVL72 is a property of the rack design rather than of the cabling plan, and is generated from the ResourceType.

### location ↔ `rack inventory header / netautogen rack object` (import)

| NRM field | System field | Notes |
|---|---|---|
| `site` | `site` |  |
| `room` | `room` |  |
| `row` | `row` |  |
| `rack` | `rack` |  |
| `rack_unit` | `rack_unit` |  |
| `observation` | `_constant` | via `constant_expected` |

**Cannot be carried:**

`cooling_zone`
: Not in a rack inventory file either. Which CDU or manifold group serves a rack position is a facility fact, and it arrives from Nautobot or from the commissioning survey.
`coordinates`
: Rack inventory files address a position by rack and rack unit, never by room-relative metres. Coordinates come from the facility floor plan.
`power_zone`
: Facility power zoning is not in a rack inventory file. It comes from Nautobot or from the facility drawing.

## `cyclonedx`

**Role:** export target

**Authority:** Authoritative for nothing. This is a rendering of NRM for consumers with CycloneDX tooling. If a
BOM and NRM disagree, NRM is right and the BOM is stale.


**Join key:** `id` ↔ `component.bom-ref`

**Not mapped:** `location`, `domain`, `port`, `link`, `cooling-path`

### resource ↔ `component (type=device)` (export)

| NRM field | System field | Notes |
|---|---|---|
| `id` | `component.bom-ref` |  |
| `name` | `component.name` |  |
| `parent_id` | `component.components[] nesting` | via `nest_by_containment` — NRM's containment tree becomes CycloneDX's nested components, which is the one structural feature the two share. |
| `identifiers[format=SERIAL].value` | `component.properties["nvis:serial"]` | CycloneDX 1.6 has no first-class serial field for hardware components, so identifiers go into namespaced properties. Namespaced because an unprefixed custom property collides with someone else's the first time two BOMs are merged. |
| `identifiers[format=UUID].value` | `component.properties["nvis:uuid"]` |  |
| `identifiers[format=IB_GUID].value` | `component.properties["nvis:ib-guid"]` |  |
| `identifiers[format=GPU_UUID].value` | `component.properties["nvis:gpu-uuid"]` |  |
| `external_refs.nautobot` | `component.externalReferences[type=other]` |  |

**Cannot be carried:**

`domain_id`
: No CycloneDX concept of a logical domain.
`lifecycle`
: CycloneDX 1.6 lifecycles describe the BOM's own phase, not a component's operational state. Mapping one onto the other would be a false cognate.
`observation`
: CycloneDX has no expected/observed distinction. A BOM is implicitly a statement about reality, so only `observed` resources should be exported -- exporting planned ones would claim hardware exists that has not shipped.
`part_location`
: No CycloneDX equivalent. Available as a property if a consumer asks for it.

### resource-type ↔ `component (type=device) manufacturer/model fields` (export)

Type data is FLATTENED onto each component, because CycloneDX has no type/instance split.
This is the main information loss in the export and the reason it is one-way: re-importing
would create one ResourceType per unit.


| NRM field | System field | Notes |
|---|---|---|
| `manufacturer` | `component.manufacturer.name` |  |
| `model` | `component.name` |  |
| `part_number` | `component.properties["nvis:part-number"]` |  |
| `datasheet_url` | `component.externalReferences[type=documentation]` |  |

**Cannot be carried:**

`cooling`
: No CycloneDX concept of cooling requirements.
`port_templates`
: No CycloneDX concept of ports.
`power`
: No CycloneDX concept of power draw.

## `dcgm`

**Role:** telemetry

**Authority:** Authoritative for observed GPU health and utilization, at a scrape cadence. Not an inventory
source: it knows only the GPUs on hosts it runs on, has no view of anything else in the rack, and
keeps no history NRM should mirror.


**Join key:** `identifiers[format=GPU_UUID].value` ↔ `UUID`

**Not mapped:** `resource-type`, `location`, `port`, `link`, `cooling-path`

### resource ↔ `DCGM_FI_DEV_* metric labels` (export)

The GPU Resource already exists in NRM from Redfish discovery or the inventory file. This
mapping identifies WHICH one a metric belongs to, and supplies the topology labels DCGM has
no way to know.


| NRM field | System field | Notes |
|---|---|---|
| `identifiers[format=GPU_UUID].value` | `UUID` | The join key. Present on every dcgm-exporter metric. |
| `name` | `Hostname` | **unreliable** — DCGM's Hostname is the GPU's HOST, not the GPU itself -- so it matches the host node's Resource.name, not the GPU Resource's. Marked unreliable because that off-by-one-level mismatch is easy to wire up wrongly and produces a dashboard that looks right. |
| `part_location.location_ordinal_value` | `gpu` | DCGM's `gpu` label is the device index within the host, which is the ordinal within the parent -- exactly Redfish PartLocation's LocationOrdinalValue. Note the index is not stable across reboots on all platforms, so it is a display aid and never a join key. |
| `attributes.pci_bus_id` | `pci_bus_id` |  |
| `external_refs.dcgm` | `device` |  |

**Cannot be carried:**

`lifecycle`
: Deliberately NOT mapped from DCGM health. A throttling GPU is not a lifecycle change, and writing telemetry into a lifecycle field would make the inventory flap with load and give two systems different answers about the same GPU.
`observation`
: Telemetry is observed by definition, but it is not an inventory observation. The GPU's existence is asserted by discovery; DCGM only reports on it.
`resource_type_id`
: DCGM reports a modelName string, which is a display name rather than a SKU. Type comes from discovery.

### domain ↔ `Prometheus relabel target labels` (export)

What NRM contributes back to the observability stack: rack, cooling path and domain labels
attached to every GPU metric. This is what makes "show me GPU throttling by cooling path" a
query instead of a correlation exercise across two systems.


| NRM field | System field | Notes |
|---|---|---|
| `name` | `nvis_domain` |  |
| `domain_class` | `nvis_domain_class` |  |

**Cannot be carried:**

`member_resource_ids`
: A label set is per-target. Membership is expressed by every member carrying the domain label, not by a list on the domain.
`owner`
: Deliberately not exported as a metric label. Owner changes on a human cadence and would create a new time series on every reorganization, which is how a Prometheus instance acquires millions of dead series.

## `nautobot`

**Role:** source of record

**Authority:** Authoritative for asset existence, ownership, lifecycle and physical placement. NOT authoritative
for observed topology, fabric state, or telemetry.


**Join key:** `id` ↔ `custom_fields.resource_id`

**Not mapped:** `domain`

### resource-type ↔ `dcim.DeviceType` (import)

Nautobot splits the catalog across DeviceType, ModuleType, RackType and InventoryItem.
NRM has one ResourceType with a `resource_class` discriminator, so the mapping is
many-to-one and `resource_class` is what records which Nautobot model it came from.


| NRM field | System field | Notes |
|---|---|---|
| `id` | `custom_fields.resource_id` |  |
| `manufacturer` | `manufacturer.name` |  |
| `model` | `model` |  |
| `part_number` | `part_number` |  |
| `u_height` | `u_height` |  |
| `is_full_depth` | `is_full_depth` |  |
| `weight_kg` | `weight` | via `to_kg` — Nautobot carries weight_unit separately; normalize to kilograms on import. |
| `datasheet_url` | `comments` | **unreliable** — Nautobot has no datasheet field, and in practice the URL lands in comments. Mapped so the value is not lost, marked unreliable so no automated check depends on parsing it. |
| `labels` | `tags` | via `tags_to_labels` |

**Cannot be carried:**

`cooling`
: Nautobot 4.7's liquid-cooling model covers cooling TOPOLOGY, not per-SKU cooling requirements. Design flow and max inlet temperature come from the partner datasheet and have no Nautobot home, so NRM is the source for them.
`port_templates`
: Partially expressible as Nautobot InterfaceTemplate, but only for ethernet and IB. Coolant and NVLink port templates have no equivalent, so mapping half of them would make a generated port list silently incomplete. See the port entity below.
`power`
: Nautobot models power ports and feeds, not nameplate SKU figures. TDP in particular is a cooling-sizing input with no Nautobot field.

### location ↔ `dcim.Location` (import)

Nautobot's Location is a recursive tree typed by LocationType, so site/room/row arrive as
ancestors rather than as fields. `flatten_ancestors` walks that tree; the reverse direction
requires the LocationTypes to already exist, which is why this is import-only.


| NRM field | System field | Notes |
|---|---|---|
| `id` | `custom_fields.resource_id` |  |
| `site` | `ancestors[location_type=Site].name` | via `flatten_ancestors` |
| `room` | `ancestors[location_type=Room].name` | via `flatten_ancestors` |
| `row` | `ancestors[location_type=Row].name` | via `flatten_ancestors` |
| `rack` | `rack.name` |  |
| `rack_unit` | `rack.position` |  |
| `rack_face` | `rack.face` |  |
| `power_zone` | `rack.power_panel.name` | **unreliable** — Approximate. Nautobot models PowerPanel per feed, and a rack may draw from more than one; this takes the first. Adequate for grouping, not for a redundancy audit. |

**Cannot be carried:**

`coordinates`
: Nautobot has no room-relative coordinate fields. NRM is the source.
`grid_reference`
: No Nautobot field. Commonly a custom field per site, so not portable.

### resource ↔ `dcim.Device` (both)

Also maps from dcim.Module, dcim.InventoryItem and dcim.Rack depending on resource_class.
Device is the common case and the one this mapping is written against.


| NRM field | System field | Notes |
|---|---|---|
| `id` | `custom_fields.resource_id` |  |
| `name` | `name` |  |
| `resource_type_id` | `device_type.custom_fields.resource_id` |  |
| `parent_id` | `parent_bay.device.custom_fields.resource_id` | Nautobot expresses containment through DeviceBay for devices and through `device` for modules and inventory items. NRM has one parent_id for all of them. |
| `location_id` | `location.custom_fields.resource_id` |  |
| `lifecycle` | `status.name` | via `status_map` |
| `identifiers[format=SERIAL].value` | `serial` | Nautobot's flat `serial` becomes one member of NRM's identifiers array with format SERIAL and scope set to the manufacturer, since serials are not globally unique. |
| `identifiers[format=UUID].value` | `asset_tag` | **unreliable** — Only when the asset tag is genuinely a UUID. Sites use asset_tag for barcode labels too, so an importer must check the shape rather than assume it. |
| `external_refs.nautobot` | `id` | Nautobot's own primary key, so NRM can link back to the object. |
| `labels` | `tags` | via `tags_to_labels` |
| `domain_id` | `cluster.custom_fields.resource_id` | **unreliable** — Nautobot Cluster is virtualization-oriented. It fits a compute domain reasonably and an IB fabric or NVLink domain not at all, so most Domain records have no Nautobot origin. |

**Cannot be carried:**

`observation`
: THE significant gap, and the reason NRM exists as a profile rather than as a Nautobot view. Nautobot records intent -- everything in it is `expected`. It has no way to say "this is what ibnetdiscover actually saw", so plan-versus-reality cannot be expressed there at all. Every observed record in NRM is NRM-native.
`part_location`
: Nautobot DeviceBay position is coarser than Redfish PartLocation and cannot address a transceiver inside a cage inside a tray.

### port ↔ `dcim.Interface` (both)

Nautobot splits terminations by kind: Interface (ethernet/IB), ConsolePort, PowerPort,
FrontPort/RearPort (patching), and 4.7's CoolingIntake/CoolingOutflow. NRM has one Port with
`port_class`, so port_class selects which Nautobot model a record round-trips to.


| NRM field | System field | Notes |
|---|---|---|
| `id` | `custom_fields.resource_id` |  |
| `name` | `name` |  |
| `resource_id` | `device.custom_fields.resource_id` |  |
| `port_class` | `type` | via `interface_type_map` — Nautobot's `type` conflates medium and class in one enum (`100gbase-x-qsfp28`), which NRM splits into port_class plus media plus speed_gbps. The transform is lossy in the export direction and must pick a representative Nautobot type. |
| `media` | `type` | via `interface_type_map` |
| `speed_gbps` | `speed` | via `kbps_to_gbps` |
| `admin_state` | `enabled` | via `bool_to_admin_state` |
| `identifiers[format=MACAddress].value` | `mac_address` |  |
| `labels` | `tags` | via `tags_to_labels` |

**Cannot be carried:**

`breakout_of`
: Nautobot models breakouts as parent/child Interfaces, which is close, but the semantics differ enough (child interfaces there are also used for VLAN subinterfaces) that automatic mapping would conflate two unrelated things.
`observation`
: As for Resource -- Nautobot has no observed/expected distinction.

### link ↔ `dcim.Cable` (both)

Nautobot Cable is a physical connection between two terminations, which is NRM's expected
physical link. NRM's logical links -- an NVLink over a cartridge -- have no Nautobot
equivalent and stay NRM-native.


| NRM field | System field | Notes |
|---|---|---|
| `id` | `custom_fields.resource_id` |  |
| `a_port_id` | `termination_a.custom_fields.resource_id` |  |
| `b_port_id` | `termination_b.custom_fields.resource_id` |  |
| `cable.cable_type` | `type` |  |
| `cable.length_m` | `length` | via `to_metres` — Nautobot carries length_unit separately; normalize to metres. |
| `operational_state` | `status.name` | via `cable_status_map` |
| `labels` | `tags` | via `tags_to_labels` |

**Cannot be carried:**

`key`
: NRM-native and derived, not stored anywhere in Nautobot. Computed from the endpoints on import by contracts.identity.link_key.
`speed_gbps`
: Nautobot stores negotiated speed on the Interface, not the Cable. Available via the endpoints rather than directly.
`supporting_link_id`
: Nautobot has no link-layering concept, so an NVLink cannot be recorded as supported by its cable cartridge. This is the field that makes "six NVLink faults, one bad cartridge" a query instead of an investigation, and it has no Nautobot home.

### cooling-path ↔ `dcim.CoolingSource` (both)

Nautobot 4.7 shipped CoolingSource -> CoolingFeed -> CoolingIntake/CoolingOutflow, which is
the model NRM's CoolingPath adopts field-for-field. This is why the contract needs no RDF:
the IT/OT requirement turned out to be expressible relationally, so Brick and Haystack stay
documented export targets rather than dependencies.


| NRM field | System field | Notes |
|---|---|---|
| `id` | `custom_fields.resource_id` |  |
| `name` | `name` |  |
| `source_resource_id` | `device.custom_fields.resource_id` |  |
| `coolant` | `coolant_type` |  |
| `design.flow_lpm` | `flow_rate` | via `to_lpm` |
| `design.supply_temp_c` | `supply_temperature` |  |
| `design.return_temp_c` | `return_temperature` |  |
| `feed_resource_ids` | `cooling_feeds[].device.custom_fields.resource_id` |  |
| `intake_port_id` | `cooling_intake.custom_fields.resource_id` |  |
| `outflow_port_id` | `cooling_outflow.custom_fields.resource_id` |  |

**Cannot be carried:**

`cooled_resource_ids`
: Derivable in Nautobot by walking feeds to intakes to devices, but not stored. NRM denormalizes it deliberately -- it is the blast radius of a cooling fault and is read on every alert.
`design.heat_capacity_kw`
: No Nautobot field. This is the figure compared against the summed TDP of the cooled resources, which is the check that catches an under-cooled rack before it throttles.
`loop`
: Nautobot does not distinguish facility-primary from technology-secondary loops. The distinction matters because the two are owned by different organizations and a fault on either side presents identically at the rack.
`redundancy`
: No Nautobot field for source redundancy tier.

## `redfish`

**Role:** discovery

**Authority:** Authoritative for the OBSERVED composition of one system: which parts are installed, their
serials and firmware, and the chassis-relative position of each. Not authoritative for anything
beyond the chassis boundary -- Redfish has no view of the rack, the fabric or the facility.


**Join key:** `identifiers[format=UUID].value` ↔ `ComputerSystem.UUID`

**Not mapped:** `location`, `domain`, `link`

### resource ↔ `Chassis / ComputerSystem / Processor / NetworkAdapter` (import)

Redfish's resource tree maps onto NRM's containment tree almost directly, which is the whole
reason containment was chosen as the primary relationship. `Links.ContainedBy` becomes
parent_id with no reinterpretation.


| NRM field | System field | Notes |
|---|---|---|
| `name` | `Name` |  |
| `parent_id` | `Links.ContainedBy` | via `resolve_odata_id` |
| `identifiers[format=UUID].value` | `UUID` |  |
| `identifiers[format=SERIAL].value` | `SerialNumber` | Scope the identifier with Manufacturer, since serials are not globally unique. |
| `identifiers[format=GPU_UUID].value` | `Processors[].UUID` | **unreliable** — Only for GPU processors, and only where the platform reports the GPU- prefixed form. Where it does not, DCGM is the reliable source for GPU UUID. |
| `part_location` | `Location.PartLocation` | Field-for-field. PartLocation is adopted verbatim in common.schema.json, so no transformation is required or permitted. |
| `lifecycle` | `Status.State` | via `redfish_state_map` |
| `attributes.firmware_version` | `FirmwareVersion` | An attribute rather than a modelled field because firmware version is per-component and changes on a different cadence from everything else in the model. It is here because "which nodes are on the old BF3 BIOS" is a question asked at every bring-up. |
| `observation` | `_constant` | via `constant_observed` |

**Cannot be carried:**

`domain_id`
: No Redfish concept of a logical domain.
`location_id`
: Redfish Location is chassis-relative. Some platforms report a rack name in Location.Placement, but not reliably enough to build on.
`resource_type_id`
: Redfish reports Manufacturer and Model as strings, not a catalog reference. An importer resolves them against existing ResourceTypes; minting one per discovered string would fill the catalog with variant spellings of the same SKU.

### resource-type ↔ `Chassis Manufacturer + Model + PartNumber` (import)

Enough to MATCH an existing ResourceType, not enough to create a good one -- a Redfish
payload has no rack units, no TDP and no cooling requirement. Partner datasheets fill those.


| NRM field | System field | Notes |
|---|---|---|
| `manufacturer` | `Manufacturer` |  |
| `model` | `Model` |  |
| `part_number` | `PartNumber` |  |

**Cannot be carried:**

`cooling`
: Redfish ThermalSubsystem reports observed temperatures and pump state, not the design coolant requirement.
`port_templates`
: Derivable from a specific system's NetworkAdapter list, but that is instance data, not the SKU's port layout.
`power`
: Redfish Power/PowerSubsystem reports MEASURED draw and capacity, not the SKU's nameplate figures. Those are different numbers answering different questions, and conflating them would make a power budget wrong in a way that looks plausible.
`u_height`
: Not reported by Redfish. From the datasheet.

### port ↔ `NetworkPort / NetworkDeviceFunction / Port` (import)

| NRM field | System field | Notes |
|---|---|---|
| `name` | `Id` |  |
| `resource_id` | `Links.ContainedBy` | via `resolve_odata_id` |
| `port_class` | `PortProtocol` | via `redfish_protocol_map` |
| `identifiers[format=MACAddress].value` | `AssociatedNetworkAddresses` |  |
| `speed_gbps` | `CurrentSpeedGbps` |  |
| `media` | `ActiveLinkTechnology / PluggableModuleType` | **unreliable** — via `redfish_media_map` — Reporting varies by platform and firmware. |
| `part_location` | `Location.PartLocation` |  |
| `admin_state` | `LinkEnabled` | via `bool_to_admin_state` |
| `observation` | `_constant` | via `constant_observed` |

**Cannot be carried:**

`breakout_of`
: Redfish models this as Port.Links.AssociatedNetworkPorts, whose semantics differ enough from a breakout relationship that mapping it automatically would conflate two things.

### cooling-path ↔ `ThermalSubsystem / CoolingLoop / Pump` (import)

Redfish 2023.2 added CoolingLoop and CoolingUnit, which gives an in-chassis view of the loop.
It stops at the chassis boundary, so the facility side of a path -- CDU, manifold, primary
loop -- comes from Nautobot 4.7 or is NRM-native.


| NRM field | System field | Notes |
|---|---|---|
| `name` | `CoolingLoop.Id` |  |
| `coolant` | `CoolingLoop.Coolant.CoolantType` | via `redfish_coolant_map` |
| `design.supply_temp_c` | `CoolingLoop.SupplyEquipmentNames` | **unreliable** — Redfish reports MEASURED supply temperature in Sensors, not the design point. Mapped only where a platform publishes a design threshold; otherwise the design figures are NRM-native and come from commissioning. |
| `observation` | `_constant` | via `constant_observed` |

**Cannot be carried:**

`cooled_resource_ids`
: Derivable within one chassis, but a path serves a whole rack.
`design.heat_capacity_kw`
: Not reported by Redfish, and not knowable from inside one chassis -- rated heat removal is a property of the facility loop. This is the figure compared against summed TDP to catch an under-cooled rack before it throttles, so its absence here matters.
`feed_resource_ids`
: The distribution chain is outside the chassis and therefore outside Redfish.
`loop`
: Redfish sees one loop from inside the chassis and cannot tell facility-primary from technology-secondary.
`redundancy`
: Redfish reports pump redundancy for a CoolingUnit, which is not the same as the redundancy tier of the facility source serving the path.

## `ufm`

**Role:** discovery

**Authority:** Authoritative for OBSERVED InfiniBand topology and link state: which GUIDs exist, which ports
are up, what width and rate they negotiated, and what is cabled to what. Not authoritative for
asset identity, physical placement, or intent -- UFM knows a node by GUID and has no idea which
rack it is in.


**Join key:** `identifiers[format=IB_GUID].value` ↔ `node_guid`

**Not mapped:** `resource-type`, `location`, `cooling-path`

### resource ↔ `ibnetdiscover node / UFM /resources/systems` (import)

A discovered node produces a Resource with observation=observed. Reconciliation against the
expected inventory happens on IB_GUID; where no expected record matches, the node is real and
unplanned, which is itself a finding worth reporting.


| NRM field | System field | Notes |
|---|---|---|
| `name` | `node_description` | **unreliable** — node_description is operator-set and frequently the hostname, but it is not guaranteed unique or even populated. Useful for a human-readable report, never as a join key -- that is what the GUID is for. |
| `identifiers[format=IB_GUID].value` | `node_guid` |  |
| `external_refs.ufm` | `system_id` |  |
| `lifecycle` | `severity` | via `ufm_severity_map` |
| `observation` | `_constant` | via `constant_observed` |

**Cannot be carried:**

`location_id`
: UFM has no physical placement. Location comes from the expected inventory and is attached during reconciliation, which is a large part of the value of doing the reconciliation.
`parent_id`
: UFM's node list is flat; containment comes from the expected inventory.
`resource_type_id`
: UFM reports a device type string, not a catalog SKU. An importer must resolve it to an existing ResourceType or leave the resource unresolved -- minting a ResourceType from a discovery string would fill the catalog with near-duplicate junk entries.

### port ↔ `ibnetdiscover port / UFM /resources/ports` (import)

| NRM field | System field | Notes |
|---|---|---|
| `name` | `port_number` | via `ib_port_name` |
| `resource_id` | `node_guid` | via `resolve_by_ib_guid` |
| `port_class` | `_constant` | via `constant_infiniband` |
| `identifiers[format=IB_GUID].value` | `port_guid` |  |
| `speed_gbps` | `active_speed / active_width` | via `ib_rate_to_gbps` — IB reports width and speed separately (4X NDR). The product is the usable figure, and it is what a negotiated-rate check compares against the expected value. |
| `lanes` | `active_width` | via `ib_width_to_lanes` |
| `admin_state` | `logical_state` | via `ib_state_to_admin` |
| `observation` | `_constant` | via `constant_observed` |

**Cannot be carried:**

`media`
: UFM reports the cage type inconsistently across firmware versions. Media comes from the ResourceType's port template, which is reliable.
`part_location`
: No physical position information in UFM.

### link ↔ `ibnetdiscover link / UFM /resources/links` (import)

This is the entity the whole crosswalk exists for. An observed link here and an expected link
from the cabling file compute the same content-addressable key, so plan-versus-reality is a
set difference: missing-in-observed is an uncabled or dead link, missing-in-expected is a
miscable, and present-in-both-at-different-speeds is a marginal link.


| NRM field | System field | Notes |
|---|---|---|
| `key` | `source_port_node_description_port : dest_port_node_description_port` | via `link_key` |
| `a_port_id` | `source_port_guid` | via `resolve_port_by_ib_guid` |
| `b_port_id` | `dest_port_guid` | via `resolve_port_by_ib_guid` |
| `link_class` | `_constant` | via `constant_infiniband` |
| `speed_gbps` | `active_speed / active_width` | via `ib_rate_to_gbps` |
| `operational_state` | `physical_state` | via `ib_phys_state_map` |
| `observation` | `_constant` | via `constant_observed` |
| `cable.length_m` | `cable_length` | **unreliable** — Read from the cable EEPROM, which is populated by the vendor and sometimes wrong. |
| `cable.part_number` | `cable_pn` |  |
| `cable.cable_type` | `cable_type` |  |

**Cannot be carried:**

`supporting_link_id`
: UFM sees the IB link, not the physical cartridge carrying it. Layering is established during reconciliation against the expected inventory.

### domain ↔ `UFM fabric / subnet` (import)

| NRM field | System field | Notes |
|---|---|---|
| `name` | `fabric_name` |  |
| `domain_class` | `_constant` | via `constant_ib_fabric` |
| `external_refs.ufm` | `subnet_prefix` |  |

**Cannot be carried:**

`owner`
: UFM has no ownership concept. Owner is an NVIS fact and is the first thing an escalation needs, so it is NRM-native.
