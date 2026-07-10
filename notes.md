We are going to write a program that syncs the data povided by our "swob-ml" partners down to a local 
directory structure. The intent is that we can re-run this program to download the files that may have
been previously unavailable for a given time period, this will require storing some state and I'm open
to suggestions on the best format for that, but with a preference for a flat file that is loaded when
the program starts. SQLite should be avoided as we tend to use NFS based storage.

The data is provided by the following URL format:  https://hpfx.collab.science.gc.ca/{day}/WXO-DD/observations/swob-ml/partners/{partner}/{day}/{station}/{file}

day is a YYYYMMDD formatted date
there are numerous partners but the one we care about for a given execution will be passed as
a command line parameter

Directories prior to the file will provide directory listings so we can use those for discovery of 
available data. Within each day will be many stations, we want to discover and download them all.

It is expected that each day will be fully synced when all 24 hourly data files are downloaded 

This will be a python program that runs from the command line, my intent being that we can run it from
a task runner (currently kestra). The output of this program should be twofold: the synced data files
themselves in a directory structure that looks like: {specified dir}/{partner}/cache/day and a manifest 
of those files which were added or changed during the last run. this manifest will be passed to our
ingestion program to bring those files into our database.

We should use standard python libraries where possible. 

Deployment should be done as a docker container from which we'll execute the command line program. We'll
Set up a github action for automated publishing. 