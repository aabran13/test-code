import os
from os import listdir
from os.path import isfile,join
import json
import time
import shutil
import getpass
import threading
import csv
import logging

from netmiko import ConnectHandler
from netmiko.ssh_exception import NetMikoTimeoutException
from paramiko.ssh_exception import SSHException
import paramiko
import MySQLdb
import textfsm
import pandas as pd



#set working directory for tmp files
wd = ('/home/{user dir}/python/temp/')
#set up threading to utilize (max_threads count) concurrent SSH connections
threads = []
max_threads = 100
sema = threading.BoundedSemaphore(value=max_threads)

# Prompt for user credentials
tuser = raw_input("Enter TACACS Username: ")
tpass = getpass.getpass("Enter TACACS Password: ")
muser = raw_input("Enter MySQL Username: ")
mpass = getpass.getpass("Enter MySQL Password: ")


#-----------------------------------------------------------
def del_temp_files():
    '''
    Delete temporary files that were created on the previous run
    '''
    # temp_files_dir = (wd)
    list_temp_dir = os.listdir(wd)
    ext = (".json",".csv",".txt",".log")
    for item in list_temp_dir:
        if item.endswith(ext):
            os.remove(os.path.join(wd, item))

#------------------------------------------------------------
def get_db():
    '''
    MySQL connection
    '''
    # assgin var for MySQL database connection
    db = MySQLdb.connect(host="localhost",
                         user=muser,
                         passwd=mpass,
                         db=muser #my muser is the same name as my database
                         )
    return db

#-----------------------------------------------------------
def devices_list():
    '''
    Pull list of IPs from MySQL to pass onto netmiko connections
    '''
    cursor = db.cursor()
    cursor.execute("SELECT DISTINCT IP FROM *TABLE WHERE *FEILD LIKE 'string' AND  *FEILD LIKE '%string%' limit 10")
    items = cursor.fetchall()
    devices = [x[0] for x in items] #convert tuple to list
    #print (devices)

    return devices

#------------------------------------------------------------
#open SSH connection to device
def ssh_connection(ip, username, password):
    try:
        return ConnectHandler(device_type='cisco_xr',
                                ip=ip,
                                username=username,
                                password=password,
                                global_delay_factor=2)

    except Exception as error:
        logger.error('. %&%&%&%&%&  {}   \t   {}'.format(ip, error))
        with open (wd +"conn_error.txt", "a") as efile:
            efile.write(ip+"\n")

#--------------------------------------------------------------
def get_worker(ip,device):
    '''
     Gather info using NTC Templates for output
    '''
    try:

        print("Connecting to "+ip)
        set_term = device.send_command("terminal length 0")
        cdp_info = device.send_command('show cdp neighbor detail', use_textfsm=True)

        #inserting additional information loop
        for x in cdp_info:
            #insert IP of device into dict for identification purposes
            x["ip"] = ip
            # print(x["dest_host"].split(".")[0])
            # these hostnames sometimes have .domain-name.net. I split that out as I do not need/want the domain name
            x["dest_host"] = x["dest_host"].split(".")[0]
            x["sysname"] = x["sysname"].split(".")[0]



        with open (wd +"temp_cdp_info_"+(ip)+".json", "w") as file1:
            json.dump(cdp_info,file1)

    except Exception as error:
        print("Get_ERROR - " +str(error) + " " + str(ip))
        logger.error(". Get Error    {}   \t    {}".format(ip, error))
        #change file path to your directory
        with open (wd +"conn_error.txt", "a") as efile:
            if 'unicode' in str(error):
                with open (wd +"conn_error_unicode.txt", "a") as efile2:
                    efile2.write(ip+"\n")
                    devices.remove(ip)
            else:
                efile.write(ip+"\n")
#--------------------------------------------------------------
def retry_errors():
    '''
    Retrying devices that were logged in the expection section of get_worker
    '''

    if os.path.isfile(wd +'conn_error.txt'):
        print("Retrying errors")
        hosts = open(wd +"conn_error.txt", "r").readlines()

        for host in hosts:
            try:

                host = host.rstrip("\n")
                device = ConnectHandler(device_type="cisco_xr",
                                        ip=host,
                                        username=tuser,
                                        password=tpass,
                                        global_delay_factor=2,
                                        verbose=False
                                        )
                print("Connecting to "+host)

                set_term = device.send_command("terminal length 0")
                cdp_info = device.send_command('show cdp neighbor detail', use_textfsm=True)

                #inserting additional information loop
                for x in cdp_info:
                    #insert IP of device into dict for identification purposes
                    x["ip"] = host
                    # print(x["dest_host"].split(".")[0])
                    # these hostnames sometimes have .domain-name.net. I split that out as I do not need/want the domain name
                    x["dest_host"] = x["dest_host"].split(".")[0]
                    x["sysname"] = x["sysname"].split(".")[0]


                with open (wd + "temp_cdp_info_"+(host)+".json", "w") as file1:
                    json.dump(cdp_info,file1)

            except Exception as error:
                print ("SECOND_ERROR - " +str(error) + "" + str(host))
                logger.error(". Get Error    {}   \t    {}".format(host, error))


#-------------------------------------------------------------
def wait_time():
        try:
            while ("temp_cdp_info_" + devices[-1] + ".json") not in os.listdir(wd):
                print("Waiting...")
                time.sleep(5)
        except Exception as e100:
            print("DEVICE LIST ERROR: " + str(e100))

#-------------------------------------------------------------
def conv_csv():
    '''
    Convert JSON to CSV
    '''
    path = (wd)
    os.chdir(wd)
    print("Converting files to CSV")
    for file in os.listdir(path):
        if file.endswith(".json"):
            out_filename = file.split(".json")[0]
            df=pd.read_json(file)
            df.to_csv("results_"+ out_filename +".csv", header=False, index=False)

#-------------------------------------------------------------
def insert_data():
    '''
    Insert data from CSV file into MySQL
    '''
    print("Sending data to MySQL")
    os.chdir(wd)
    cursor = db.cursor()
    try:
        for item in os.listdir(wd):
            if item.endswith(".csv"):
                csv_data = csv.reader(file(item))
                for row in csv_data:
                    #print(row)
                    cursor.execute('INSERT INTO cdp_info(capabilities, dest_host, ip, local_port, mgmt_ip, platform, remote_port, sysname, version) \
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(row))
        db.commit()
        cursor.close()
        #print ('INSERTED MYSQL: ' +(row))
        print("MySQL transfer complete")
    except Exception as e:
        print("Something went wrong")
        print(e)
        db.rollback()
        db.close()

#--------------------------------------------------------------

def main(ip, username, password):
    # connect to device via SSH
    device = ssh_connection(ip, username, password)

    #if we can't connect, release the lock and move on
    if device == None:
        sema.release()
        return

    # call get_data function to run commands
    output = get_worker(ip, device)

    sema.release()


if __name__ == '__main__':
    start_time = time.time()
    # Delete files created from past run
    del_temp_files()
    #set up logging
    logger = logging.getLogger("LOG")
    handler = logging.FileHandler(wd +"main.log")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    paramiko.util.log_to_file(wd +"paramiko.log")
    #set up MySQL connection
    db = get_db()
    #grab list of IP addresses
    devices = devices_list()
    #start main function
    for host in devices:
        sema.acquire()
        thread = threading.Thread(target=main, args=(host, tuser, tpass))
        threads.append(thread)
        thread.start()

    # wait for last ip in list to create file in wd
    wait_time()
    # Retry any errors
    retry_errors()
    # convert .json to .csv
    conv_csv()
    # insert data to MySQLdb
    insert_data()

    elapsed_time = time.time() - start_time
    print("Script run time = " + time.strftime("%H:%M:%S", time.gmtime(elapsed_time)))
