# Pure Storage Flash Array - File POD Clone
A Python script to clone a pod on a Pure Flash array with an NFS file export.

# Note:  This script uses the pypureclient Python library.

# Theory of Operation:
This script is designed to use the "pod-clone" feature of a Pure Storage Flash Array to quickly clone a pod with an exported NFS file system.

The snapshot functionality of Purity's FA file delivers a read-only copy of the files in the file system.  To provide a writeable copy, the file system needs to be put into a pod, and then cloned, and re-exported.  The pod-clone functionalty is instant and consumes minimal space as the two exported file systems are fully deduplicated.  This script automates the entire process.

After the pod has been cloned and exported, the exported file systems may be mounted in the guest OS.

# Usage:
The script takes several arguments:
-f the name of a JSON file which may include the FA address and API token, and how to export the cloned pod.
-s the name of the soure pod to clone
-t the name of the new pod that will be created
-e the extension to add to the cloned file exports in Purity (e.g. if the source pod has file exports "data" and "logs", and the extension is specified as "clone", the cloned pod will export file systems "dataclone" and "datalogs".  To specify a hypen, use curly braces: {-}clone )

# Sample:
$ python fa_pod_cp.py -f sample.json -s source-pod -t clone-pod -e {-}clone

# A sample JSON file:
The repository includes a sample JSON file which includes:
- the fully qualified name of the Flash Array
- the API token to use to authenticate against the Flash Array
- the NFS export files to use for the cloned file systems
- the clients authorized to access the cloned pod (use "*" for any client)
- the permissions for the cloned pod (e.g. RW or RO)

# Flash Array authentication
The script will use the provided JSON file to read the IP or FQDN of the Flash Array, and an API token to use to authenticate.
Alternatively, if the JSON file does not provide these, the script will look for the OS variables FA_HOST and API_TOKEN.



