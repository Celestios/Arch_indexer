"""Generate scip_pb2.py from scip.proto. Run before build or after updating scip.proto."""
import subprocess
import sys

def main():
    result = subprocess.run(
        [sys.executable, "-m", "grpc_tools.protoc",
         "--python_out=src/engines", "--proto_path=.", "scip.proto"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("Generated src/engines/scip_pb2.py from scip.proto")

if __name__ == "__main__":
    main()
