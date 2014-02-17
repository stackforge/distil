import os
from csv import writer
from artifice import invoice
# from artifice import clerk_mixins
from decimal import *


class Csv(invoice.RatesFileMixin, invoice.Invoice):

    def __init__(self, tenant, start, end, config):
        self.config = config
        self.tenant = tenant
        self.lines = {}
        self.closed = False
        self.start = start
        self.end = end
        self.total = Decimal(0.0)

    def bill(self):
        """Genearates the lines for a sales order for the stored tenant."""
        # Usage is one of VMs, Storage, or Volumes.
        for resource in self.tenant.resources.values():
            print " * " + resource.metadata['type']

            print "   - resource id: " + str(resource.id)
            self.add_line(resource.metadata['type'], [resource.id])

            headers = []
            values = []
            for key, value in resource.metadata.iteritems():
                print "   - " + key + ": " + str(value)
                headers.append(key + str(":"))
                values.append(value)

            self.add_line(resource.metadata['type'], headers)
            self.add_line(resource.metadata['type'], values)

            headers = ["service:", "usage:", "rate:", "cost:"]
            self.add_line(resource.metadata['type'], headers)

            total_cost = Decimal(0.0)

            for service in resource.services.values():
                appendee = []
                cost = Decimal(0.0)
                usage = Decimal(service.volume)

                # GET REGION FROM CONFIG:
                region = 'wellington'

                rate = self.rate(service.name, region)
                cost = usage * rate
                total_cost += cost
                appendee.append(service.name)
                appendee.append(usage)
                appendee.append(rate)
                appendee.append(round(cost, 2))
                print "   - " + service.name + ": " + str(usage)
                print "     - rate: " + str(rate)
                print "     - cost: " + str(round(cost))
                self.add_line(resource.metadata['type'], appendee)

            appendee = ["total cost:", round(total_cost, 2)]
            self.add_line(resource.metadata['type'], appendee)
            print "   - total cost: " + str(round(total_cost))

            self.add_line(resource.metadata['type'], [])

            # adds resource total to sales-order total.
            self.total += total_cost

    def add_line(self, res_type, line):
        """Adds a line to the given resource type list."""
        if not self.closed:
            try:
                self.lines[res_type].append(line)
            except KeyError:
                self.lines[res_type] = [line]
            return
        raise AttributeError("Can't add to a closed invoice")

    @property
    def filename(self):
        fn_dict = dict(tenant=self.tenant.name, start=self.start,
                       end=self.end)

        fn = os.path.join(
            self.config["output_path"],
            self.config["output_file"] % fn_dict
        )
        return fn

    def close(self):
        """Closes the sales order, and exports the lines to a csv file."""
        try:
            open(self.filename)
            raise RuntimeError("Can't write to an existing file!")
        except IOError:
            pass
        fh = open(self.filename, "w")
        csvwriter = writer(fh, dialect='excel', delimiter=',')

        csvwriter.writerow(["", "from", "until"])
        csvwriter.writerow(["usage range: ", str(self.start), str(self.end)])
        csvwriter.writerow([])

        for key in self.lines:
            for line in self.lines[key]:
                csvwriter.writerow(line)
            csvwriter.writerow([])

        # write a blank line
        csvwriter.writerow([])
        # write total
        csvwriter.writerow(["invoice total cost: ", round(self.total, 2)])

        fh.close()
        self.closed = True
