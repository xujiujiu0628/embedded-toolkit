#!/usr/bin/env python3
"""
svd_to_json.py — CMSIS SVD XML to deterministic JSON extraction

Extracts peripheral register definitions from ARM CMSIS SVD files.
Zero AI involvement — register addresses, bit positions, and field names
are parsed deterministically from the XML.

Usage:
    python svd_to_json.py --svd STM32F103xx.svd --periph I2C1
    python svd_to_json.py --svd STM32F103xx.svd --all --out knowledge/peripherals/
    python svd_to_json.py --svd STM32F103xx.svd --list    # list all peripherals

SVD source locations for STM32F103:
    - CubeMX: ~/STM32Cube/db/mcu/STM32F103C8Tx.xml (may need conversion)
    - Keil Pack: D:/KEIL5/ARM/Pack/Keil/STM32F1xx_DFP/x.x.x/CMSIS/SVD/STM32F103xx.svd
    - ST GitHub: https://github.com/STMicroelectronics/cmsis-device-f1
    - Community: https://github.com/posborne/cmsis-svd (mirrors)

Output schema compatible with stm32f103-ref.json "peripherals" format.
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET


def parse_bit_range(bit_range_str):
    """Parse CMSIS SVD bitRange '[msb:lsb]' into (offset, width)."""
    s = bit_range_str.strip().lstrip('[').rstrip(']')
    msb, lsb = s.split(':')
    msb, lsb = int(msb), int(lsb)
    offset = lsb
    width = msb - lsb + 1
    return offset, width


def parse_dim_element_group(reg_elem):
    """Parse dimElementGroup for register arrays (e.g., TIM2_CCR[1..4]).

    Returns list of (name_suffix, dim_index) tuples, or [(None, None)] if not an array.
    """
    dim = reg_elem.find('dim')
    dim_increment = reg_elem.find('dimIncrement')
    dim_index_text = reg_elem.find('dimIndex')
    if dim is None or dim_increment is None:
        return [(None, None)]

    dim_count = int(dim.text, 0) if dim.text else 1
    incr = int(dim_increment.text, 0) if dim_increment.text else 0

    indices = []
    if dim_index_text is not None and dim_index_text.text:
        indices = [s.strip() for s in dim_index_text.text.split(',')]
    else:
        indices = [str(i) for i in range(dim_count)]

    # Build suffix: replace %s placeholder in name, or append index
    name_elem = reg_elem.find('name')
    base_name = name_elem.text if name_elem is not None and name_elem.text else ''
    has_placeholder = '%s' in base_name

    result = []
    for i, idx in enumerate(indices[:dim_count]):
        suffix = idx if has_placeholder else f'_{idx}'
        result.append((suffix, i))
    return result


def resolve_derived_from(reg_elem, all_registers, peripheral_name):
    """Resolve derivedFrom attribute by copying fields from base register."""
    derived = reg_elem.get('derivedFrom')
    if not derived:
        return reg_elem

    base = all_registers.get(derived)
    if base is None:
        print(f"Warning: {peripheral_name}: derivedFrom '{derived}' not found",
              file=sys.stderr)
        return reg_elem

    # Merge: child elements override parent
    merged = base.copy() if hasattr(base, 'copy') else base
    # For simplicity, just copy fields if child has none
    if reg_elem.find('fields') is None and base.find('fields') is not None:
        # Deep copy fields from base
        pass  # Handled during field extraction

    return reg_elem


def extract_fields(reg_elem, all_registers):
    """Extract bit fields from a register element."""
    fields = {}
    fields_elem = reg_elem.find('fields')
    if fields_elem is None:
        return fields

    # Check derivedFrom for field inheritance
    derived = reg_elem.get('derivedFrom')
    base_fields = {}
    if derived and derived in all_registers:
        base_reg = all_registers[derived]
        base_fields_elem = base_reg.find('fields')
        if base_fields_elem is not None:
            for f in base_fields_elem.findall('field'):
                name_elem = f.find('name')
                if name_elem is not None and name_elem.text:
                    base_fields[name_elem.text] = f

    for field_elem in fields_elem.findall('field'):
        name_elem = field_elem.find('name')
        if name_elem is None or not name_elem.text:
            continue
        name = name_elem.text

        desc_elem = field_elem.find('description')
        desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ''

        # Parse bit position
        bit_range = field_elem.find('bitRange')
        bit_offset = field_elem.find('bitOffset')
        bit_width = field_elem.find('bitWidth')

        if bit_range is not None and bit_range.text:
            offset, width = parse_bit_range(bit_range.text)
            bit_key = str(offset) if width == 1 else f"{offset}:{offset+width-1}"
        elif bit_offset is not None and bit_offset.text:
            offset = int(bit_offset.text, 0)
            width = int(bit_width.text, 0) if bit_width is not None and bit_width.text else 1
            bit_key = str(offset) if width == 1 else f"{offset}:{offset+width-1}"
        else:
            continue

        # Access type
        access_elem = field_elem.find('access')
        access = access_elem.text if access_elem is not None and access_elem.text else ''

        field_info = {"name": name}
        if desc:
            field_info["desc"] = desc
        if access and access != 'read-write':
            field_info["access"] = access

        # Enumerated values
        enum = field_elem.find('enumeratedValues')
        if enum is not None:
            values = {}
            for ev in enum.findall('enumeratedValue'):
                v_name = ev.find('name')
                v_value = ev.find('value')
                v_desc = ev.find('description')
                if v_name is not None and v_name.text and v_value is not None and v_value.text:
                    entry = {"value": v_value.text}
                    if v_desc is not None and v_desc.text:
                        entry["desc"] = v_desc.text.strip()
                    values[v_name.text] = entry
            if values:
                field_info["enum"] = values

        fields[bit_key] = field_info

    # Add base fields not overridden by child
    for bname, bfield in base_fields.items():
        already_present = any(
            f.get('name') == bname for f in fields.values()
        )
        if not already_present:
            b_name_elem = bfield.find('name')
            b_desc_elem = bfield.find('description')
            b_bit_offset = bfield.find('bitOffset')
            b_bit_width = bfield.find('bitWidth')
            if b_name_elem is not None and b_name_elem.text:
                b_offset = int(b_bit_offset.text, 0) if b_bit_offset is not None and b_bit_offset.text else 0
                b_width = int(b_bit_width.text, 0) if b_bit_width is not None and b_bit_width.text else 1
                b_key = str(b_offset) if b_width == 1 else f"{b_offset}:{b_offset+b_width-1}"
                fields[b_key] = {
                    "name": b_name_elem.text,
                    "desc": b_desc_elem.text.strip() if b_desc_elem is not None and b_desc_elem.text else '',
                }

    return fields


def extract_registers(periph_elem, all_periphs=None):
    """Extract all registers from a peripheral element.

    Handles peripheral-level derivedFrom (e.g. USART2 derivedFrom USART1,
    TIM3 derivedFrom TIM2): inherits the base peripheral's <registers>.
    """
    registers = {}
    regs_elem = periph_elem.find('registers')
    if regs_elem is None:
        derived = periph_elem.get('derivedFrom')
        if derived and all_periphs and derived in all_periphs:
            return extract_registers(all_periphs[derived], all_periphs)
        return registers

    # First pass: collect all register elements by name (for derivedFrom resolution)
    all_reg_elems = {}
    for reg_elem in regs_elem.findall('register'):
        name_elem = reg_elem.find('name')
        if name_elem is not None and name_elem.text:
            all_reg_elems[name_elem.text] = reg_elem

    # Second pass: extract each register
    for reg_elem in regs_elem.findall('register'):
        name_elem = reg_elem.find('name')
        if name_elem is None or not name_elem.text:
            continue
        base_name = name_elem.text

        # Handle register arrays (dimElementGroup)
        dims = parse_dim_element_group(reg_elem)
        for dim_suffix, dim_idx in dims:
            if dim_suffix is not None:
                reg_name = base_name.replace('%s', dim_suffix) if '%s' in base_name else base_name + dim_suffix
            else:
                reg_name = base_name

            desc_elem = reg_elem.find('description')
            desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ''

            offset_elem = reg_elem.find('addressOffset')
            if offset_elem is None or not offset_elem.text:
                continue
            offset = offset_elem.text

            # Apply dimIncrement for array registers
            if dim_idx is not None and dim_idx > 0:
                dim_incr = reg_elem.find('dimIncrement')
                if dim_incr is not None and dim_incr.text:
                    offset = f"0x{int(offset, 16) + dim_idx * int(dim_incr.text, 0):04X}"

            size_elem = reg_elem.find('size')
            size = size_elem.text if size_elem is not None and size_elem.text else '32'

            access_elem = reg_elem.find('access')
            access = access_elem.text if access_elem is not None and access_elem.text else ''

            reset_elem = reg_elem.find('resetValue')
            reset = reset_elem.text if reset_elem is not None and reset_elem.text else ''

            reg_info = {"offset": offset}
            if desc:
                reg_info["desc"] = desc
            if size and size != '32':
                reg_info["size"] = size
            if access and access != 'read-write':
                reg_info["access"] = access
            if reset and reset != '0x00000000':
                reg_info["reset"] = reset

            # Extract bit fields
            fields = extract_fields(reg_elem, all_reg_elems)
            if fields:
                reg_info["bits"] = fields

            registers[reg_name] = reg_info

    return registers


# STM32F103C8T6 = medium-density (64KB Flash): SVD 中真实存在的外设
# 31 个可用 / 22 个不可用（high-density/connectivity/大封装独有）
C8_UNAVAILABLE = {
    "ADC3", "DAC", "DMA2", "FSMC",
    "GPIOD", "GPIOE", "GPIOF", "GPIOG",
    "SDIO", "SPI3",
    "TIM5", "TIM6", "TIM7", "TIM8", "TIM9",
    "TIM10", "TIM11", "TIM12", "TIM13", "TIM14",
    "UART4", "UART5",
}


def merge_into_ref(all_data: dict, ref_path: str) -> tuple[int, int]:
    """Merge SVD-extracted peripherals into stm32f103-ref.json.

    Existing FULL peripherals and _relationships/memory_map are kept
    untouched. New peripherals get available_on_c8 annotation.
    Returns (added, total_after).
    """
    with open(ref_path, 'r', encoding='utf-8') as f:
        ref = json.load(f)

    existing = ref["peripherals"]
    added = 0
    for name, data in sorted(all_data.items()):
        if name in existing:
            continue  # 已有 FULL 外设（含手工语义数据）一字不动
        data = dict(data)
        data["available_on_c8"] = name not in C8_UNAVAILABLE
        existing[name] = data
        added += 1

    ref["_meta"]["version"] = "2.0.0"
    ref["_meta"]["updated"] = "2026-08-12"
    ref["_meta"]["peripheral_count"] = len(existing)

    with open(ref_path, 'w', encoding='utf-8') as f:
        json.dump(ref, f, ensure_ascii=False, indent=2)
    return added, len(existing)


def extract_peripheral(periph_elem, all_periphs=None):
    """Extract a single peripheral from SVD (resolves peripheral-level derivedFrom)."""
    name_elem = periph_elem.find('name')
    if name_elem is None or not name_elem.text:
        return None, None
    name = name_elem.text

    desc_elem = periph_elem.find('description')
    desc = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ''

    base_elem = periph_elem.find('baseAddress')
    base = base_elem.text if base_elem is not None and base_elem.text else '0x00000000'

    group_elem = periph_elem.find('groupName')
    group = group_elem.text if group_elem is not None and group_elem.text else ''

    # Determine bus from group name (heuristic)
    bus_map = {
        'APB1': 'APB1', 'APB2': 'APB2', 'AHB': 'AHB',
        'ADC': 'APB2', 'TIM1': 'APB2', 'TIM8': 'APB2',
        'USART1': 'APB2', 'SPI1': 'APB2', 'GPIO': 'APB2',
        'AFIO': 'APB2', 'EXTI': 'APB2',
        'TIM': 'APB1', 'USART': 'APB1', 'SPI': 'APB1',
        'I2C': 'APB1', 'IWDG': 'APB1', 'WWDG': 'APB1',
        'RTC': 'APB1', 'BKP': 'APB1', 'PWR': 'APB1',
        'CAN': 'APB1', 'USB': 'APB1', 'DAC': 'APB1',
        'DMA': 'AHB', 'CRC': 'AHB', 'FLASH': 'AHB',
        'RCC': 'AHB', 'SDIO': 'AHB', 'FSMC': 'AHB',
    }
    bus = '?'
    for key, b in bus_map.items():
        if key in name or (group and key in group):
            bus = b
            break

    registers = extract_registers(periph_elem, all_periphs)

    # Build interrupt info
    interrupts = []
    int_elems = periph_elem.findall('interrupt')
    for ie in int_elems:
        int_name = ie.find('name')
        int_value = ie.find('value')
        if int_name is not None and int_name.text:
            irq = {"name": int_name.text}
            if int_value is not None and int_value.text:
                irq["value"] = int(int_value.text, 0)
            desc_e = ie.find('description')
            if desc_e is not None and desc_e.text:
                irq["desc"] = desc_e.text.strip()
            interrupts.append(irq)

    data = {
        "base": base,
        "bus": bus,
        "desc": desc,
        "registers": registers,
    }
    if interrupts:
        data["interrupts"] = interrupts

    return name, data


def extract_all(peripherals_elem):
    """Extract all peripherals from SVD (two-pass for derivedFrom resolution)."""
    elems = peripherals_elem.findall('peripheral')
    name_map = {}
    for pe in elems:
        n = pe.find('name')
        if n is not None and n.text:
            name_map[n.text] = pe
    result = {}
    for pe in elems:
        name, data = extract_peripheral(pe, name_map)
        if name and data:
            result[name] = data
    return result


def extract_single(svd_path, target_periph):
    """Extract a single peripheral (streaming parse for large files)."""
    for event, elem in ET.iterparse(svd_path, events=('end',)):
        if elem.tag == 'peripheral':
            name_elem = elem.find('name')
            if name_elem is not None and name_elem.text:
                if name_elem.text.upper() == target_periph.upper():
                    name, data = extract_peripheral(elem)
                    elem.clear()
                    return name, data
            elem.clear()
    return None, None


def list_peripherals(svd_path):
    """List all peripheral names in the SVD file."""
    names = []
    for event, elem in ET.iterparse(svd_path, events=('end',)):
        if elem.tag == 'peripheral':
            name_elem = elem.find('name')
            if name_elem is not None and name_elem.text:
                desc_elem = elem.find('description')
                desc = desc_elem.text.strip()[:80] if desc_elem is not None and desc_elem.text else ''
                base_elem = elem.find('baseAddress')
                base = base_elem.text if base_elem is not None and base_elem.text else '?'
                names.append({"name": name_elem.text, "base": base, "desc": desc})
            elem.clear()
    return names


def main():
    parser = argparse.ArgumentParser(
        description="CMSIS SVD XML → JSON deterministic register extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python svd_to_json.py --svd STM32F103xx.svd --list
  python svd_to_json.py --svd STM32F103xx.svd --periph I2C1
  python svd_to_json.py --svd STM32F103xx.svd --periph I2C1 --json
  python svd_to_json.py --svd STM32F103xx.svd --all --out knowledge/peripherals/
SVD sources:
  Keil Pack: D:/KEIL5/ARM/Pack/Keil/STM32F1xx_DFP/*/CMSIS/SVD/STM32F103xx.svd
  ST GitHub: https://github.com/STMicroelectronics/cmsis-device-f1
        """
    )
    parser.add_argument("--svd", required=True, help="Path to CMSIS SVD XML file")
    parser.add_argument("--periph", default=None, help="Extract single peripheral by name")
    parser.add_argument("--all", action="store_true", help="Extract all peripherals")
    parser.add_argument("--list", action="store_true", help="List all peripherals in the SVD")
    parser.add_argument("--out", default=None, help="Output directory for --all (one JSON per peripheral)")
    parser.add_argument("--merge", default=None,
                        help="Merge extracted peripherals into existing ref.json (with --all)")
    parser.add_argument("--json", action="store_true", help="JSON output (otherwise human-readable)")
    args = parser.parse_args()

    if not os.path.exists(args.svd):
        print(f"Error: SVD file not found: {args.svd}", file=sys.stderr)
        print("SVD files are typically found in:", file=sys.stderr)
        print("  Keil Pack: D:/KEIL5/ARM/Pack/Keil/STM32F1xx_DFP/*/CMSIS/SVD/", file=sys.stderr)
        print("  CubeMX:    ~/STM32Cube/db/mcu/", file=sys.stderr)
        print("  ST GitHub: https://github.com/STMicroelectronics/cmsis-device-f1", file=sys.stderr)
        sys.exit(1)

    # --list: quick scan
    if args.list:
        periphs = list_peripherals(args.svd)
        print(f"\nPeripherals in {args.svd}:")
        print(f"{'Name':<20} {'Base':<12} Description")
        print("-" * 72)
        for p in sorted(periphs, key=lambda x: x['name']):
            print(f"{p['name']:<20} {p['base']:<12} {p['desc']}")
        print(f"\nTotal: {len(periphs)} peripherals")
        return

    # --periph: single extraction (memory efficient)
    if args.periph:
        name, data = extract_single(args.svd, args.periph)
        if name is None:
            print(f"Error: Peripheral '{args.periph}' not found in SVD", file=sys.stderr)
            sys.exit(1)

        if args.json:
            print(json.dumps({name: data}, ensure_ascii=False, indent=2))
        else:
            print(f"\n=== {name} ===\n")
            print(f"Base: {data['base']}  Bus: {data['bus']}")
            print(f"Description: {data['desc']}")
            if 'interrupts' in data:
                print(f"Interrupts: {json.dumps(data['interrupts'], ensure_ascii=False)}")
            print(f"\nRegisters ({len(data['registers'])}):")
            for rname, rdata in sorted(data['registers'].items()):
                fields = rdata.get('bits', {})
                n_fields = len(fields)
                desc = rdata.get('desc', '')
                print(f"  {rname:<20} @ {rdata['offset']:<6}  {desc[:60]}")
                if n_fields:
                    for bit_pos, finfo in sorted(fields.items()):
                        fname = finfo.get('name', '?')
                        fdesc = finfo.get('desc', '')[:50]
                        enum_note = ''
                        if 'enum' in finfo:
                            vals = list(finfo['enum'].keys())
                            enum_note = f"  enum: {', '.join(vals[:5])}"
                        print(f"    bit {bit_pos}: {fname} — {fdesc}{enum_note}")
            print()
        return

    # --all: full extraction
    if args.all:
        tree = ET.parse(args.svd)
        root = tree.getroot()
        peripherals_elem = root.find('peripherals')
        if peripherals_elem is None:
            print("Error: No <peripherals> element found in SVD", file=sys.stderr)
            sys.exit(1)

        all_data = extract_all(peripherals_elem)

        if args.merge:
            added, total = merge_into_ref(all_data, args.merge)
            print(f"Merged {added} new peripherals into {args.merge} "
                  f"(total peripherals: {total})")
            return

        if args.out:
            os.makedirs(args.out, exist_ok=True)
            for name, data in all_data.items():
                out_path = os.path.join(args.out, f"{name.lower()}.json")
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Extracted {len(all_data)} peripherals to {args.out}")
        else:
            print(json.dumps(all_data, ensure_ascii=False, indent=2))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
