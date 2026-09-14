#!/bin/bash

echo "=== Delete Plots ==="
rm -rf plots/*
echo "=== Done ==="
echo ""

echo "=== Delete CSVs ==="
rm -rf csv/frame_records.csv
rm -rf csv/frame_packets.csv
echo "=== Done ==="
echo ""
