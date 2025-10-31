#
# Python script to clone a Flash Array Pod with NFS exported file systems
#
# Graham Thornton - Jan 2025
# gthornton@purestorage.com
#
# usage:
# python fa_pod_cp.py -s gct-pod-ora-swingdb -t gct-pod-tmp -f export_rules.json -e xxx -x
#

import sys
import os
import re
import datetime
import json
import argparse

import warnings
warnings.filterwarnings(action='ignore')

from pypureclient import flasharray
import urllib3

# disable the HTTPS warnings
urllib3.disable_warnings()

# global variables
halt=1
nohalt=0
terminate=0
version = "1.0.0"
not_defined = "Not Defined"

# main dictionary for script variables
dictMain={}

# holds the policy names for the source and target pods
lst_source_policies=[]
lst_target_policies=[]

# holds the file system names for the source and target pods
lst_source_pod_file_system_names=[]
lst_target_pod_file_system_names=[]

#
# clean quit
#

def mQuit( message=None ):

    if( message != None ):
        print( '============' )
        print( message )

    print( '============' )
    print( 'program terminated' )
    quit()


#
# generic error handler
#

def mError( halt, return_code, message ):
    print( '============' )
    print( f'error:{message}' )
    if( return_code !=0 ): print( f'return code:{return_code}' );

    # do we need to halt execution?
    if( halt>0 ): mQuit()



##############################################

# JSON FILE PROCESSING

##############################################

#
# read json config file
#
def fReadConnectionJSON( myfile ):

    try:
        with open(myfile, 'r') as file:
            data = json.load(file)
            return data
    except FileNotFoundError:
        print(f'Note: file not found:{myfile}')
        return None
    except json.JSONDecodeError:
        print(f'Error: Invalid JSON format in:{myfile}')
        return None


##############################################

# FLASH ARRAY

##############################################

#
# connect to the flash array
#

def fFAConnect( my_flash_array, my_flash_array_api_token ):

    print( '============' )
    print( f'connecting to Flash Array:{my_flash_array}' )

    try:
        array=flasharray.Client( target=my_flash_array, api_token=my_flash_array_api_token )

        response = array.get_volumes()

        if ( response.status_code == 200): print( "connected" )
        else: mError( halt, response.status_code, response.reason )

    except:
        mError( halt, 0, 'fFAConnect failed, please check Flash Array connectivity and API token' )

    return array




#
# check that the source pod exists and that the target pod does not
#

def mCheckPodExists( my_array, my_source_pod, my_target_pod ):

    source_found=0

    try:
        response = my_array.get_pods()
    except:
        mError( halt, response.status_code, response.errors[0].message )

    if ( response.status_code != 200 ): mError( halt, response.status_code, response.errors[0].message )

    #print( response.total_item_count )
    num_pods=0
    for mypod in response.items:
        num_pods += 1
        if( mypod.name == my_source_pod ): source_found=1
        if( mypod.name == my_target_pod ): mError( halt, 0, 'target pod '+my_target_pod+' exists, please destroy and eradicate the target, or choose a different target pod name' )
        #  print( mypod )

    if ( source_found==0 ): mError( halt, 0, 'source pod '+my_source_pod+' was not found on this Flash Array' )




#
# find the policies on the source pod
# for each policy found, replace the source pod name with the target pod name
# populates the lst_source_policies and lst_target_policies
#

def mQueryPolicies( my_array, my_source_pod, my_target_pod ):

    try:
        response = my_array.get_policies_nfs()
    except:
        terminate = mError( halt, response.status_code, response.errors[0].message )

    if ( response.status_code != 200 ): mError( halt, response.status_code, response.errors[0].message )

    for policy in response.items:
        # see if this policy is for the source_pod
        #print( policy )
        try:
            pod_policy_name = policy.pod.name
        except:
            pod_policy_name = ''

        if ( pod_policy_name == my_source_pod ):
            print( 'policy '+policy.name )
            lst_source_policies.append( policy.name )
            lst_target_policies.append( policy.name.replace( my_source_pod, my_target_pod ))

    # check this pod actually has policies
    if ( len(lst_source_policies) == 0 ): mError( nohalt, 0, 'source pod does not appear to have any policies' )

    print( f'number of policies found:{len(lst_source_policies)}' )
    #print( lst_source_policies )
    #print( lst_target_policies )




#
# find the relevant rules for the source pod policies
# we may have to alter the rule to change/limit the client who can access the exported directory
#

def mQueryNFSClientRules( my_array, my_source_pod, my_lst_source_policies ):

    counter=0
    rules=0

    while( counter < len( my_lst_source_policies )):

        mypolicy = my_lst_source_policies[counter];

        print( f'rules for policy:{mypolicy}' )

        try:
            response = my_array.get_policies_nfs_client_rules( policy_names=[mypolicy] )

            for rule in response.items:
            #    print( rule )
                rules+=1

        except:
            print( f'no policies found for:{mypolicy}' )

        #print( response.items  )

        counter+=1

    print( f'{rules} rule(s) found' )


#
# check that the cloned pod export directories do not already exist
# code will append the export_suffix to each currently exported directory
# and then make sure an export directory that name does not already exist
#

def mQueryCreateExports( my_array, my_export_suffix, my_lst_source_policies ):

    # get the directory exports from the source pod
    try:
        response = my_array.get_directory_exports( policy_names=my_lst_source_policies )
    except:
        mError( halt, response.status_code, response.errors[0].message )

    if ( response.status_code != 200 ): mError( halt, response.status_code, response.errors[0].message )

    # step through the exports
    for my_directory_export in response.items:

        # convert the policy and directory names by replacing the source pod name with the target pod name
        target_export_name = my_directory_export.export_name+my_export_suffix

        # check to see if this export already exists - it should not
        # we should get a 400 status on this call
        try:
            response2 = my_array.get_directory_exports( export_names=[target_export_name] )
        except:
            mError( halt, response2.status_code, 'get_directory_exports call returned an error' )

        # if we got a 200 code the export already exists under a different pod
        if( response2.status_code==200 ):

            print( f'cannot create target export directory:{target_export_name}' )

            # step through the matching records we got back to see which pods this export directory already exists in
            for my_directory_export_exists in response2.items:

                print( f'directory already exists for policy:{my_directory_export_exists.policy.name}' )
                print( f'directory already for directory:{my_directory_export_exists.directory.name}' )
                #print( my_directory_export_exists )

            #print( response.status_code )
            mError( halt, response2.status_code, 'select an alternative export suffix' )




#
# find the file systems for the source pod
# file systems will have the naming convetion POD::FILESYSTEM
# we will replace the POD with the new pod name and
# create a list of new filesystems in lst_target_pod_file_system_names
#

def mQueryFileSystems( my_array, my_source_pod, my_target_pod ):

    try:
        response = my_array.get_file_systems()
    except:
        mError( halt, response.status_code, response.errors[0].message )

    if ( response.status_code != 200 ): mError( halt, response.status_code, response.errors[0].message )

    # step through the list of file systems returned
    for file_system in response.items:

        # try to see if this file system has a pod, some do not
        try:
            pod_name = file_system.pod.name

            # this file system is part of a pod, check if it is the source_pod
            if( pod_name == my_source_pod ):

                print( f'file system {file_system.name}' )

                # this file system is part of the source pod
                # add it to the list and generate a new name for the cloned file system
                lst_source_pod_file_system_names.append( file_system.name )
                lst_target_pod_file_system_names.append( file_system.name.replace( my_source_pod, my_target_pod ))

        except:
            pod_name = ''
            #print( 'not part of a pod' )

    # check this pod actually has some file systems
    if ( len(lst_source_pod_file_system_names) == 0 ): mError( nohalt, 0, 'source pod does not appear to have any NFS file systems' )

    print( f'number of source pod file systems found:{len(lst_source_pod_file_system_names)}' )




#
# clone the pod
#

def mClonePod( my_array, my_source_pod, my_target_pod ):

    mypod={
     'name': my_target_pod ,
     'quota_limit': 0,
     'requested_promotion_state': 'promoted',
     'source': {'name': my_source_pod },
    }

    try:
        response = my_array.post_pods( names=[my_target_pod], pod=mypod )
    except:
        mError( halt, response.status_code, response.errors[0].message )

    if ( response.status_code != 200 ): mError( halt, response.status_code, response.errors[0].message )



#
# apply directory exports to the cloned pod
# we gather the exports for the source systems and then
# replace the source pod name with the target pod name
# a suffix is added to the export names
#

def mApplyDirectoryExports( my_array, safe_mode, my_source_pod, my_target_pod, my_export_suffix, my_lst_source_policies ):

    print( f'getting directory exports for {my_source_pod}' )

    #print( lst_source_pod_file_system_names )

    #
    try:
        response = my_array.get_directory_exports( policy_names=my_lst_source_policies )
    except:
        mError( halt, response.status_code, response.errors[0].message )

    if ( response.status_code != 200 ): mError( halt, response.status_code, response.errors[0].message )

    # step through the exports
    for my_directory_export in response.items:

        # convert the policy and directory names by replacing the source pod name with the target pod name
        target_export_name = my_directory_export.export_name+my_export_suffix
        target_directory_name = my_directory_export.directory.name.replace( my_source_pod, my_target_pod )
        target_policy_name = my_directory_export.policy.name.replace( my_source_pod, my_target_pod )

        # create the export name
        myexport={
            'export_name': target_export_name,
            'path': '/',
        }

        # check for safety lock
        if( safe_mode ):

            print( f'NOTE: clone of {my_directory_export.export_name} would be exported as {target_export_name}' )

        else:

            # try to add the export
            try:
                response2 = my_array.post_directory_exports( directory_names=[ target_directory_name ], exports=myexport, policy_names=[ target_policy_name ] )
            except:
                mError( halt, response2.status_code, response.errors[0].message )

            if ( response2.status_code != 200 ): mError( halt, response2.status_code, response.errors[0].message )

            print( f'clone of {my_directory_export.export_name} exported as {target_export_name}' )



#
# change the export policy rules
# we have to read the existing policy rule names,
# delete them, and then add new ones
#

def mChangeExportRules( my_array, my_export_rules, my_target_pod, my_lst_target_policies ):

    export_rules = {'rules': my_export_rules}

#    print( export_rules ) 

    # get a list of policies with NFS rules
    try:
        response = my_array.get_policies_nfs_client_rules( policy_names=my_lst_target_policies )
    except:
        mError( halt, response.status_code, response.errors[0].message )

    if ( response.status_code != 200 ): mError( halt, response.status_code, response.errors[0].message )


    # for each rule we got back:
    for rule in response.items:

        try:
            rule_name = rule.name
            rule_policy_name = rule.policy.name

            print( f'deleting rule:{rule.name} for policy:{rule_policy_name}' )

            # we have to delete the old rule first
            try:
                response2 = my_array.delete_policies_nfs_client_rules( names=[rule_name], policy_names=[rule_policy_name] )
            except:
                mError( halt, response2.status_code, response.errors[0].message )

            if ( response2.status_code != 200 ): mError( halt, response2.status_code, response.errors[0].message )

            # now we can add a new rule
            print( f'adding new rule for policy:{rule_policy_name}' )

            try:
                response3 = my_array.post_policies_nfs_client_rules( policy_names=[rule_policy_name], rules=export_rules )
            except:
                mError( halt, response3.status_code, response.errors[0].message )

            if ( response3.status_code != 200 ): mError( halt, response3.status_code, response.errors[0].message )

        # general catch all
        except:
            print( 'NOTE: rule not changed' )



##############################################

# MAIN BLOCK

##############################################

def doMain( ):

    print( '============' )
    print( f'fa_pod_cp.py {version} started at {datetime.datetime.now()}' )

    # parse the command line args
    parser = argparse.ArgumentParser(
                    prog='fa_pod_cp ', usage='%(prog)s [options]',
                    description='clone a pod of NFS file system(s) on a Pure Flash Array',
                    epilog='coded by Graham Thornton - gthornton@purestorage.com')

    parser.add_argument('-s','--source_pod', help='name of the source pod', required=True)
    parser.add_argument('-t','--target_pod', help='name of target pod to be created', required=True)
    parser.add_argument('-e','--export_suffix', help='suffix to append to cloned file system exports' )
    parser.add_argument('-f','--config_file', help='json document of config options', required=True)
    parser.add_argument('-x','--execute_lock', action='store_false', help="specify -x to actually clone the pod (default is safety lock on)")

    args = parser.parse_args()

    #
    # read the config file
    #
    dictMain={}
    if( args.config_file != None ): dictMain = fReadConnectionJSON( args.config_file )

    # fa variables
    flash_array = dictMain.get( "flash_array_host", os.environ.get('FA_HOST') )
    flash_array_api_token = dictMain.get( "flash_array_api_token", os.environ.get('API_TOKEN') )

    if( flash_array==None or flash_array_api_token==None ):
        mQuit( 'flash_array_host and flash_array_api_token need to be defined in the config file or environment variables' )

    #
    # connect to the FA
    #
    myArray = fFAConnect( flash_array, flash_array_api_token )

    #
    # determine the suffix to use for the cloned file systems
    #
    export_suffix = ''

    if args.export_suffix is not None:
        export_suffix = args.export_suffix.replace("{","").replace("}","")

    print( '============' )
    print( f'cloning pod {args.source_pod} to {args.target_pod}' )






    # check source pod exists and target pod does not
    print( '============' )
    print( 'checking for existence of source-pod and non-existence of target-pod' )

    mCheckPodExists( myArray, args.source_pod, args.target_pod )



    # read the NFS policies of the source pod
    print( '============' )
    print( f'determining relevant policies for {args.source_pod}' )

    mQueryPolicies( myArray, args.source_pod, args.target_pod )



    # read the NFS client rules for the source pod
    print( '============' )
    print( f'determining client rules for NFS policies for {args.source_pod}' )

    mQueryNFSClientRules( myArray, args.source_pod, lst_source_policies )



    # check we can create the export directories
    if( len( export_suffix ) >0 ):

        print( '============' )
        print( 'checking that target export directories can be created' )

        mQueryCreateExports( myArray, export_suffix, lst_source_policies )



    # read the source file systems
    print( '============' )
    print( f'determining file systems for {args.source_pod}' )

    mQueryFileSystems( myArray, args.source_pod, args.target_pod )



    # clone the pod
    print( '============' )
    print( f'cloning pod {args.source_pod} to {args.target_pod}' )

    # only do this if safety lock disabled
    if ( args.execute_lock ):

        print( 'NOTE: safety lock is engaged, so no actual pod clone will be executed' )
        print( 'NOTE: to disable add -x to arguments' )

    else:

        # clone the pod
        mClonePod( myArray, args.source_pod, args.target_pod )



    #
    # apply the policies to the cloned pod
    # despite the documentation, this has to be done one at a time.
    #

    print( '============' )
    print( f'cloning policies for {args.target_pod}' )

    policy=0
    while( policy < len( lst_source_policies )):

        # check for safety lock
        if( args.execute_lock ):

            print( f'NOTE: would clone policy {lst_source_policies[policy]} as {lst_target_policies[policy]}' )

        else:

            print( f'cloning policy {lst_source_policies[policy]} as {lst_target_policies[policy]}' )

            try:
                reponse = myArray.post_policies_nfs( names=[lst_target_policies[policy]], source_names=[lst_source_policies[policy]] )
            except:
                mError( halt, response.status_code, response.errors[0].message )

        policy+=1



    #
    # change the export policy rules
    # we have to read the existing policy rule names,
    # delete them, and then add new ones
    #

    print( '============' )

    # check for safety lock
    if( args.execute_lock ):

        print( 'safety lock engaged, since no clone was made there are no policies to modify' )

    else:

        # get the export rules from the dictionary
        my_export_rules  = dictMain.get( "rules", not_defined )

        # if we dont have any rules, stop here
        if( my_export_rules == not_defined ):

            print( 'rule override not specified, NFS export rules will be copied as-is' )

        else:

            print( f'changing NFS export policy rules for {args.target_pod}' )
            mChangeExportRules( myArray, my_export_rules, args.target_pod, lst_target_policies )



    #
    # apply directory exports to the cloned pod
    # we gather the exports for the source systems and then
    # replace the source pod name with the target pod name
    # a suffix is added to the export names
    #

    print( '============' )

    if( len( export_suffix ) ==0 ):

        print( 'no export suffix specified so cloned file systems will not be exported' )

    else:

        mApplyDirectoryExports( myArray, args.execute_lock, args.source_pod, args.target_pod, export_suffix, lst_source_policies )

    print( '============' )
    print( 'pod cloning complete' )


if __name__ == "__main__": doMain()






